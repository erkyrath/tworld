
var websocket = null;
var connected = false;
var everconnected = false;

var uiprefs = {
    leftright_percent: 75,
    updown_percent: 70,
    smooth_scroll: true
};

/* When there are more than 80 lines in the event pane, chop it down to
   the last 60. */
var EVENT_TRIM_LIMIT = 80;
var EVENT_TRIM_KEEP = 60;

var KEY_RETURN = 13;
var KEY_UP = 38;
var KEY_DOWN = 40;

var NBSP = '\u00A0';

function collate_uiprefs() {
    for (var key in db_uiprefs) {
        uiprefs[key] = db_uiprefs[key];
    }
}

function build_page_structure() {
    /* Clear out the body from the play.html template. */
    $('#submain').empty();

    var topcol = $('<div>', { id: 'topcol' });
    var leftcol = $('<div>', { id: 'leftcol' });
    var localepane = $('<div>', { id: 'localepane' });
    var rightcol = $('<div>', { id: 'rightcol' });
    var bottomcol = $('<div>', { id: 'bottomcol' });
    var eventpane = $('<div>', { id: 'eventpane' });

    var tooloutline = $('<div>', { 'class': 'ToolOutline' });
    var toolheader = $('<div>', { 'class': 'ToolTitleBar' });
    tooloutline.append(toolheader);
    tooloutline.append($('<div>', { 'class': 'ToolSegment' }));
    tooloutline.append($('<div>', { 'class': 'ToolFooter' }));

    toolheader.append($('<h2>', { id: 'tool_title_title', 'class': 'ToolTitle' }));
    toolheader.append($('<div>', { id: 'tool_title_scope', 'class': 'ToolData' }));
    toolheader.append($('<h3>', { id: 'tool_title_creator', 'class': 'ToolTitle' }));
    rightcol.append(tooloutline);

    var inputline = $('<div>', { 'class': 'Input' });
    var inputprompt = $('<div>', { 'class': 'InputPrompt' });
    var inputframe = $('<div>', { 'class': 'InputFrame' });

    inputprompt.text('>');
    inputframe.append($('<input>', { id: 'eventinput', type: 'text', maxlength: '256' } ));
    inputline.append(inputprompt);
    inputline.append(inputframe);

    topcol.append(leftcol);
    leftcol.append(localepane);
    topcol.append(rightcol);
    bottomcol.append($('<div>', { id: 'bottomcol_topedge' }));
    bottomcol.append(eventpane);
    eventpane.append(inputline);

    /* Add the top-level, fully-constructed structures to the DOM last. More
       efficient this way. */
    $('#submain').append(topcol);
    $('#submain').append(bottomcol);

    toolpane_set_world('(In transition)', NBSP, '...');

    /* Apply the current ui layout preferences. */
    $('#topcol').css({ height: uiprefs.updown_percent+'%' });
    $('#bottomcol').css({ height: (100-uiprefs.updown_percent)+'%' });
    $('#leftcol').css({ width: uiprefs.leftright_percent+'%' });
    $('#rightcol').css({ width: (100-uiprefs.leftright_percent)+'%' });
}

function build_focuspane(contentls)
{
    var focuspane = $('<div>', { class: 'FocusPane FocusPaneAnimating',
                                 style: 'display:none;' });

    var focusoutline = $('<div>', { 'class': 'FocusOutline' });
    var focuscornercontrol = $('<div class="FocusCornerControl"><a href="#">Close</a></div>');
    focusoutline.append(focuscornercontrol);
    focusoutline.append($('<div>', { 'class': 'InvisibleAbovePara' }));
    for (var ix=0; ix<contentls.length; ix++) {
        focusoutline.append(contentls[ix]);
    }
    focusoutline.append($('<div>', { 'class': 'InvisibleBelowPara' }));
    focuspane.append(focusoutline);

    /* ### make this close control look and act nicer */
    focuscornercontrol.on('click', function() { focuspane_clear(); });

    return focuspane;
}

function setup_event_handlers() {
    $(document).on('keypress', evhan_doc_keypress);

    var inputel = $('#eventinput');
    inputel.on('keypress', evhan_input_keypress);
    inputel.on('keydown', evhan_input_keydown);
    
    $('#leftcol').resizable( { handles:'e', containment:'parent', distance: 10,
          resize:handle_leftright_resize, stop:handle_leftright_doneresize } );
    $('#topcol').resizable( { handles:'s', containment:'parent', distance: 10,
          resize:handle_updown_resize, stop:handle_updown_doneresize } );
    
    $('div.ui-resizable-handle').append('<div class="ResizingThumb">');

}

function open_websocket() {
    try {
        var url = 'ws://' + window.location.host + '/websocket';
        websocket = new WebSocket(url);
    }
    catch (ex) {
        eventpane_add('Unable to open websocket: ' + ex);
        display_error('The connection to the server could not be created. Possibly your browser does not support WebSockets.');
        return;
    }

    websocket.onopen = evhan_websocket_open;
    websocket.onclose = evhan_websocket_close;
    websocket.onmessage = evhan_websocket_message;
}

function display_error(msg) {
    var el = $('<div>', { 'class':'BlockError'} );
    el.text(msg);

    var localeel = $('#localepane');
    localeel.empty();
    localeel.append(el);

    focuspane_clear();
}

function toolpane_set_world(world, scope, creator) {
    $('#tool_title_title').text(world);
    $('#tool_title_scope').text(scope);
    $('#tool_title_creator').text(creator);
}

function localepane_set(text) {
    var parals = text.split('\n');
    var contentls = [];
    for (var ix=0; ix<parals.length; ix++) {
        if (parals[ix].length == 0)
            continue;
        var el = $('<p>');
        el.text(parals[ix]);
        contentls.push(el);
    }

    var localeel = $('#localepane');
    localeel.empty();
    for (var ix=0; ix<contentls.length; ix++) {
        localeel.append(contentls[ix]);
    }
}

function eventpane_add(msg, extraclass) {
    var frameel = $('#eventpane');

    /* Determine whether the event pane is currently scrolled to the bottom
       (give or take a margin of error). Note that scrollHeight is not a jQuery
       property; we have to go to the raw DOM to get it. */
    var atbottom = (frameel.get(0).scrollHeight - (frameel.scrollTop() + frameel.outerHeight()) < 40);

    var cls = 'Event';
    if (extraclass)
        cls = cls + ' ' + extraclass;
    var el = $('<div>', { 'class':cls} );
    el.text(msg);
    $('.Input').before(el);

    /* If there are too many lines in the event pane, chop out the early
       ones. That's easy. Keeping the apparent scroll position the same --
       that's harder. */
    var eventls = $('#eventpane .Event');
    var curcount = eventls.size();
    if (curcount > EVENT_TRIM_LIMIT) {
        var firstkeep = curcount - EVENT_TRIM_KEEP;
        var remls = eventls.slice(0, firstkeep);
        /* Calculate the vertical extent of the entries to remove, *not
           counting the top margin*. (We have a :first-child top margin
           to give the top edge of the pane some breathing room.) This
           margin calculation uses a possibly undocumented feature of
           query -- $.css(e, p, true) returns a number instead of a "16px"
           string. Hope this doesn't bite me on the toe someday.
        */
        var remheight = $(eventls[firstkeep]).position().top - $(eventls[0]).position().top - $.css(eventls[0], 'marginTop', true);
        frameel.scrollTop(frameel.scrollTop() - remheight);
        remls.remove();
    }

    /* If we were previously scrolled to the bottom, scroll to the new 
       bottom. */
    if (atbottom) {
        var newscrolltop = frameel.get(0).scrollHeight - frameel.outerHeight() + 2;
        if (!uiprefs.smooth_scroll)
            frameel.scrollTop(newscrolltop);
        else
            frameel.stop().animate({ 'scrollTop': newscrolltop }, 200);
    }
}

function focuspane_clear()
{
    /* If any old panes are in the process of sliding up or down, we
       kill them unceremoniously. */
    var oldel = $('.FocusPaneAnimating');
    if (oldel.length) {
        oldel.remove();
    }

    /* If an old pane exists, slide it out. (The call is "slideUp", even
       though the motion will be downwards. jQuery assumes everything is
       anchored at the top, but we are anchored at the bottom.) */
    var el = $('.FocusPane');
    if (el.length) {
        el.addClass('FocusPaneAnimating');
        el.slideUp(200, function() { el.remove(); });
    }
}

function focuspane_set(text)
{
    var parals = text.split('\n');
    var count = 0;

    /* We do work here to make sure that there are no empty paragraphs.
       Really the server should do this, and if the text is entirely blank,
       convert to a clear command. */
    var contentls = [];
    for (var ix=0; ix<parals.length; ix++) {
        if (parals[ix].length == 0)
            continue;
        var el = $('<p>');
        el.text(parals[ix]);
        contentls.push(el);
        count++;
    }
    if (!count) {
        var el = $('<p>');
        el.text(NBSP);
        contentls.push(el);
        count++;
    }

    /* Clear out old panes and slide in the new one. (It will have the
       'FocusPaneAnimating' class until it finishes sliding.) */

    focuspane_clear();

    var newpane = build_focuspane(contentls);
    $('#leftcol').append(newpane);
    newpane.slideDown(200, function() { newpane.removeClass('FocusPaneAnimating'); } );
}

function submit_line_input(val) {
    val = jQuery.trim(val);

    var historylast = null;
    if (eventhistory.length)
        historylast = eventhistory[eventhistory.length-1];
    
    /* Store this input in the command history for this window, unless
       the input is blank or a duplicate. */
    if (val && val != historylast) {
        eventhistory.push(val);
        if (eventhistory.length > 30) {
            /* Don't keep more than thirty entries. */
            eventhistory.shift();
        }
    }
    if (val) {
        eventhistorypos = eventhistory.length;
    }
    
    var inputel = $('#eventinput');
    inputel.val('');

    if (val) {
        var start = val.charAt(0);
        if (start == ':')
            websocket_send_json({ cmd:'pose', text:jQuery.trim(val.slice(1)) });
        else if (start == '/')
            websocket_send_json({ cmd:'meta', text:jQuery.trim(val.slice(1)) });
        else
            websocket_send_json({ cmd:'say', text:val });
    }
}

var changed_uiprefs = {};
var uipref_changed_timer = null;

function note_uipref_changed(key)
{
    changed_uiprefs[key] = true;

    /* A bit of hysteresis; we don't send uiprefs until they've been
       stable for five seconds. */
    if (uipref_changed_timer)
        cancel_delayed_func(uipref_changed_timer);
    uipref_changed_timer = delay_func(2, send_uipref_changed);
}

function send_uipref_changed()
{
    console.log('### send_uipref_changed');
    if (!connected) {
        /* Leave changed_uiprefs full of keys. Maybe we can send it later. */
        return;
    }

    var obj = {};
    for (var key in changed_uiprefs) {
        obj[key] = uiprefs[key];
    }

    websocket_send_json({ cmd:'uiprefs', map:obj });
    changed_uiprefs = {};
}

/* Event handler: keypress events on input fields.

   Move the input focus to the event pane's input line.
*/
function evhan_doc_keypress(ev) {
    var keycode = 0;
    if (ev) keycode = ev.which;

    /* If we're not scrolled to the bottom, scroll to the bottom. Yes,
       we're going to check this on every single document keystroke.
       It doesn't seem to be necessary in Safari, but it does in Firefox. */
    var frameel = $('#eventpane');
    var bottomdiff = (frameel.get(0).scrollHeight - (frameel.scrollTop() + frameel.outerHeight()));
    if (bottomdiff > 0) {
        var newscrolltop = frameel.get(0).scrollHeight - frameel.outerHeight() + 2;
        if (!uiprefs.smooth_scroll)
            frameel.scrollTop(newscrolltop);
        else
            frameel.stop().animate({ 'scrollTop': newscrolltop }, 200);
    }
    
    if (ev.target.tagName.toUpperCase() == 'INPUT') {
        /* If the focus is already on an input field, don't mess with it. */
        return;
    }

    if (ev.altKey || ev.metaKey || ev.ctrlKey) {
        /* Don't mess with command key combinations. This is not a perfect
           test, since option-key combos are ordinary (accented) characters
           on Mac keyboards, but it's close enough. */
        return;
    }

    var inputel = $('#eventinput');
    inputel.focus();

    if (keycode == KEY_RETURN) {
        /* Grab the Return/Enter key here. This is the same thing we'd do if
           the input field handler caught it. */
        submit_line_input(inputel.val());
        /* Safari drops an extra newline into the input field unless we call
           preventDefault() here. */
        ev.preventDefault();
        return;
    }

    if (keycode) {
        /* For normal characters, we fake the normal keypress handling by
           appending the character onto the end of the input field. If we
           didn't call preventDefault() here, Safari would actually do
           the right thing with the keystroke, but Firefox wouldn't. */
        /* This is completely wrong for accented characters (on a Mac
           keyboard), but that's beyond my depth. */
        if (keycode >= 32) {
            var val = String.fromCharCode(keycode);
            inputel.val(inputel.val() + val);
        }
        ev.preventDefault();
        return;
    }
}

var eventhistory = new Array();
var eventhistorypos = 0;

/* Event handler: keydown events on input fields (line input)

   Divert the up and down arrow keys to scroll through the command history
   for this window. */
function evhan_input_keydown(ev) {
  var keycode = 0;
  if (ev) keycode = ev.keyCode; //### ev.which?
  if (!keycode) return true;

  if (keycode == KEY_UP || keycode == KEY_DOWN) {
    if (keycode == KEY_UP && eventhistorypos > 0) {
      eventhistorypos -= 1;
      if (eventhistorypos < eventhistory.length)
        this.value = eventhistory[eventhistorypos];
      else
        this.value = '';
    }

    if (keycode == KEY_DOWN && eventhistorypos < eventhistory.length) {
      eventhistorypos += 1;
      if (eventhistorypos < eventhistory.length)
        this.value = eventhistory[eventhistorypos];
      else
        this.value = '';
    }

    return false;
  }

  return true;
}

/* Event handler: keypress events on input fields (line input)

   Divert the enter/return key to submit a line of input.
*/
function evhan_input_keypress(ev) {
    var keycode = 0;
    if (ev) keycode = ev.which;
    if (!keycode) return true;
    
    if (keycode == KEY_RETURN) {
        submit_line_input(this.value);
        return false;
    }
    
    return true;
}


function handle_leftright_resize(ev, ui) {
    var parentwidth = $('#submain').width();
    $('#rightcol').css({ width: parentwidth - ui.size.width });
}

function handle_leftright_doneresize(ev, ui) {
    var parentwidth = $('#submain').width();
    var percent = 100.0 * ui.size.width / parentwidth;
    if (percent < 25)
        percent = 25;
    if (percent > 85)
        percent = 85;
    var otherpercent = 100.0 - percent;
    $('#leftcol').css({ width: percent+'%' });
    $('#rightcol').css({ width: otherpercent+'%' });

    uiprefs.leftright_percent = Math.round(percent);
    note_uipref_changed('leftright_percent');
}

function handle_updown_resize(ev, ui) {
    var parentheight = $('#submain').height();
    $('#bottomcol').css({ height: parentheight - ui.size.height });
}

function handle_updown_doneresize(ev, ui) {
    var parentheight = $('#submain').height();
    var percent = 100.0 * ui.size.height / parentheight;
    if (percent < 25)
        percent = 25;
    if (percent > 85)
        percent = 85;
    var otherpercent = 100.0 - percent;
    $('#topcol').css({ height: percent+'%' });
    $('#bottomcol').css({ height: otherpercent+'%' });
    
    uiprefs.updown_percent = Math.round(percent);
    note_uipref_changed('updown_percent');
}


function evhan_websocket_open() {
    connected = true;
    everconnected = true;
}

function evhan_websocket_close() {
    websocket = null;
    connected = false;

    if (!everconnected) {
        display_error('The connection to the server could not be opened.');
    }
    else {
        display_error('The connection to the server was lost.');
    }

    /* ### set up a timer to try reconnecting. But don't change the displayed
       error unless it succeeds? */
}

function evhan_websocket_message(ev) {
    console.log('### message: ' + ev.data);
    try {
        var obj = JSON.parse(ev.data);
        var cmd = obj.cmd;
    }
    catch (ex) {
        console.log('badly-formatted message from websocket: ' + ev.data);
        return;
    }

    /*### build a command table!*/
    if (cmd == 'event')
        eventpane_add(obj.text);
    if (cmd == 'refresh') {
        localepane_set(obj.locale);
        if (obj.focus)
            focuspane_set(obj.focus);
        else
            focuspane_clear();
        if (obj.world)
            toolpane_set_world(obj.world.world, obj.world.scope, obj.world.creator);
    }
    if (cmd == 'error')
        eventpane_add('Error: ' + obj.text, 'EventError');
}

function websocket_send_json(obj) {
    if (!connected) {
        /*### Maybe only show this error once. */
        eventpane_add('Error: You are not connected to the server.', 'EventError');
        console.log('websocket not connected');
        return;
    }

    val = JSON.stringify(obj);
    websocket.send(val);
}

/* Run a function (no arguments) in timeout seconds. Returns a value that
   can be passed to cancel_delayed_func(). */
function delay_func(timeout, func)
{
    return window.setTimeout(func, timeout*1000);
}

/* Cancel a delayed function. */
function cancel_delayed_func(val)
{
    window.clearTimeout(val);
}

/* Run a function (no arguments) "soon". */
function defer_func(func)
{
    return window.setTimeout(func, 0.01*1000);
}


/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    collate_uiprefs();
    build_page_structure();
    setup_event_handlers();
    open_websocket();
});
