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

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    if (!page_sessionid) {
        /* Not actually signed in. Not sure how that's possible. */
        return;
    }

    build_page_structure();
});
