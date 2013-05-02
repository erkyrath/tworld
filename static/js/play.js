
var websocket = null;

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
    /*### try/except */
    /*### localize URL */
    websocket = new WebSocket("ws://localhost:4000/websocket");

    websocket.onopen = evhan_websocket_open;
    websocket.onclose = evhan_websocket_close;
    websocket.onmessage = evhan_websocket_message;
}

function print_event(msg) {
    var el = $('<div>', { 'class':'Event'} );
    el.text(msg);
    $('.Input').before(el);
    /*### scroll down */
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
        websocket.send(val);
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
}

function evhan_websocket_close() {
    console.log('### close');
}

function evhan_websocket_message(ev) {
    console.log('### message: ' + ev.data);
    print_event(ev.data)
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    if (!page_sessionid) {
        /* Not actually signed in. Not sure how that's possible. */
        return;
    }

    build_page_structure();
    setup_event_handlers();
    open_websocket();
});
