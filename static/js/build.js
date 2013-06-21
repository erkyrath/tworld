
/* Only called for pages with property tables. 
*/
function build_initial_proptable() {
    var tableel = $('.BuildPropTable');

    /* Remove any existing rows. */
    tableel.remove('tr');

    jQuery.each(db_props, function(index, prop) {
            var rowel = $('<tr>', { valign:'top' });
            var cellkeyel = $('<td>');
            var cellvalel = $('<td>');

            cellkeyel.append($('<span>', { 'class':'BuildPropKey' }).text(prop.key));
            cellvalel.text(''+prop.val); /*###*/

            rowel.append(cellkeyel);
            rowel.append(cellvalel);
            tableel.append(rowel);
        });
}

function setup_event_handlers() {
    var el = $('#build_location_menu');

    if (el) {
        var ls = jQuery.map(db_locations, function(loc, index) {
                return { text:loc.name, click:function() { window.location = '/build/loc/' + loc.id; } };
            });
        el.contextMenu('popup_menu',
            ls,
            { 
                leftClick: true,
                    position: { my:'left top', at:'left bottom', of:el }
            } );
    }
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    /*### install UI prefs to match play page? */
    if ($('.BuildPropTable'))
        build_initial_proptable();
    setup_event_handlers();
});
