
var property_type_selectors = [
    { value:'text', text:'Text' },
    { value:'move', text:'Move' },
    { value:'event', text:'Event' },
    { value:'value', text:'Value' }
];

function rebuild_proptable(tableel, proplist) {
    /* Remove any existing rows. */
    tableel.remove('tr');

    jQuery.each(proplist, function(index, prop) {
            var rowel = $('<tr>', { valign:'top' });
            var cellkeyel = $('<td>');
            var cellvalel = $('<td>');

            var val = '';
            var valtype = prop.val.type;
            if (valtype == 'value') {
                val = prop.val.value;
            }
            else if (valtype == 'text') {
                val = prop.val.text;
            }
            else if (valtype == 'move') {
                val = prop.val.loc; /*###*/
            }
            else if (valtype == 'event') {
                val = prop.val.text; /*###*/
            }
            else {
                valtype = 'value';
                val = '"???"';
            }

            cellkeyel.append($('<span>', { 'class':'BuildPropKey' }).text(prop.key));
            var selectel = $('<select>', { 'class':'BuildPropTypeSelect' });
            for (var ix=0; ix<property_type_selectors.length; ix++) {
                var selector = property_type_selectors[ix];
                selectel.append($('<option>', { value:selector.value }).text(selector.text));
            }
            selectel.prop('value', valtype);
            cellkeyel.append(selectel);

            cellvalel.text(val); /*###*/

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
    if (pageid == 'loc') {
        rebuild_proptable($('#build_loc_properties'), db_props);
    }
    if (pageid == 'world') {
        rebuild_proptable($('#build_world_properties'), db_world_props);
        rebuild_proptable($('#build_player_properties'), db_player_props);
    }
    setup_event_handlers();
});
