function build_page_structure() {
    $('#submain').empty();

    var topcol = $('<div>', { id: 'topcol' });
    var leftcol = $('<div>', { id: 'leftcol' });
    var localepane = $('<div>', { id: 'localepane' });
    var focuspane = $('<div>', { id: 'focuspane' });
    var rightcol = $('<div>', { id: 'rightcol' });
    var bottomcol = $('<div>', { id: 'bottomcol' });
    var eventpane = $('<div>', { id: 'eventpane' });

    topcol.append(leftcol);
    leftcol.append(localepane);
    leftcol.append(focuspane);
    topcol.append(rightcol);
    bottomcol.append($('<div>', { id: 'bottomcol_topedge' }));
    bottomcol.append(eventpane);

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
