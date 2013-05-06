
var websocket = null;
var connected = false;
var everconnected = false;

var uiprefs = {
    smooth_scroll: true
};

var KEY_RETURN = 13;
var KEY_UP = 38;
var KEY_DOWN = 40;

function build_page_structure() {
    /* Clear out the body from the play.html template. */
    $('#submain').empty();

    var topcol = $('<div>', { id: 'topcol' });
    var leftcol = $('<div>', { id: 'leftcol' });
    var localepane = $('<div>', { id: 'localepane' });
    var focuspane = $('<div>', { id: 'focuspane', style: 'display:none;' });
    var rightcol = $('<div>', { id: 'rightcol' });
    var bottomcol = $('<div>', { id: 'bottomcol' });
    var eventpane = $('<div>', { id: 'eventpane' });

    var tooloutline = $('<div>', { 'class': 'ToolOutline' });
    tooloutline.append($('<div>', { 'class': 'ToolTitleBar' }));
    tooloutline.append($('<div>', { 'class': 'ToolSegment' }));
    tooloutline.append($('<div>', { 'class': 'ToolFooter' }));
    rightcol.append(tooloutline);

    var focusoutline = $('<div>', { 'class': 'FocusOutline' });
    var focuscornercontrol = $('<div class="FocusCornerControl">Close</div>');
    focusoutline.append(focuscornercontrol);
    focusoutline.append($('<div>', { 'class': 'InvisibleAbovePara' }));
    focusoutline.append($('<p>Text.</p>'));
    focusoutline.append($('<div>', { 'class': 'InvisibleBeloePara' }));
    focuspane.append(focusoutline);

    var inputline = $('<div>', { 'class': 'Input' });
    var inputprompt = $('<div>', { 'class': 'InputPrompt' });
    var inputframe = $('<div>', { 'class': 'InputFrame' });

    inputprompt.text('>');
    inputframe.append($('<input>', { id: 'eventinput', type: 'text', maxlength: '256' } ));
    inputline.append(inputprompt);
    inputline.append(inputframe);

    topcol.append(leftcol);
    leftcol.append(localepane);
    leftcol.append(focuspane);
    topcol.append(rightcol);
    bottomcol.append($('<div>', { id: 'bottomcol_topedge' }));
    bottomcol.append(eventpane);
    eventpane.append(inputline);

    /* Add the top-level, fully-constructed structures to the DOM last. More
       efficient this way. */
    $('#submain').append(topcol);
    $('#submain').append(bottomcol);
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
    $('#localepane').empty();
    $('#localepane').append(el);

    /* ### also close the focus pane? */
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

function submit_line_input(val) {
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
        console.log('### input: ' + val);
        websocket_send_json({ cmd:'say', text:val });
    }
}

/* Event handler: keypress events on input fields.

   Move the input focus to the event pane's input line.
*/
function evhan_doc_keypress(ev) {
  var keycode = 0;
  if (ev) keycode = ev.which;

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
  /* ### save leftright percent preference, int() */
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
  /* ### save updown percent preference, int() */
}


function evhan_websocket_open() {
    console.log('### open');
    connected = true;
    everconnected = true;
}

function evhan_websocket_close() {
    console.log('### close');
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

    if (cmd == 'event')
        eventpane_add(obj.text)
    if (cmd == 'error')
        eventpane_add('Error: ' + obj.text, 'EventError')
}

function websocket_send_json(obj) {
    if (!connected) {
        console.log('websocket not connected');
        return;
    }

    val = JSON.stringify(obj);
    websocket.send(val);
}

/* Run a function (no arguments) in timeout seconds. */
function delay_func(timeout, func)
{
    return window.setTimeout(func, timeout*1000);
}

/* Run a function (no arguments) "soon". */
function defer_func(func)
{
    return window.setTimeout(func, 0.01*1000);
}


/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    build_page_structure();
    setup_event_handlers();
    open_websocket();
});
