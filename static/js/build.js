
/* Here we store all the context information for editing properties.

   "tables" is plural because we might have more than one property table
   on a page. tables[lockey] is the table for location properties;
   tables['$realm'] is realm-level, tables['$player'] is player defaults.

   A table (tableref) has this structure:
   - tablekey: location key, '$realm', '$player'
   - rootel: jQuery ref to the <table> element
   - proplist: list of prop keys, in the order displayed
   - propmap: maps prop keys to prop objects.

   A prop object (propref) has this structure:
   - key: the prop key
   - tablekey: as above
   - valtype: 'text', 'code', 'value', etc
   - rowel: jQuery ref to the <tr> element
   - areamap: maps subpane keys to <textarea> elements
   - buttonsel: jQuery ref to the <div> containing buttons
*/
var tables = {};

var NBSP = '\u00A0';

var property_type_selectors = [
    { value:'text', text:'Text' },
    { value:'code', text:'Code' },
    { value:'move', text:'Move' },
    { value:'event', text:'Event' },
    { value:'value', text:'Value' }
];

function build_proptable(tableel, proplist, tablekey) {
    var tableref = tables[tablekey];
    if (tableref === undefined) {
        tableref = { tablekey:tablekey, rootel:tableel,
                         propmap:{}, proplist:[] };
        tables[tablekey] = tableref;
    }

    /* Remove any existing rows. */
    tableel.remove('tr');

    for (var ix=0; ix<proplist.length; ix++) {
        update_prop(tableref, proplist[ix]);
    }
}

function update_prop(tableref, prop) {
    var tableel = tableref.rootel;

    var editls = [];
    var valtype = prop.val.type;
    if (valtype == 'value') {
        editls = [ { key:'value', val:prop.val.value } ];
    }
    else if (valtype == 'text') {
        editls = [ { key:'text', val:prop.val.text } ];
    }
    else if (valtype == 'code') {
        editls = [ { key:'text', val:prop.val.text } ];
    }
    else if (valtype == 'move') {
        editls = [
            { key:'loc', val:prop.val.loc, label:'Destination' },
            { key:'text', val:prop.val.text, label:'Action' },
            { key:'oleave', val:prop.val.oleave, label:'Leave' },
            { key:'oarrive', val:prop.val.oarrive, label:'Arrive' } ];
    }
    else if (valtype == 'event') {
        editls = [ 
            { key:'text', val:prop.val.text, label:'Actor' },
            { key:'otext', val:prop.val.otext, label:'Others' } ];
    }
    else {
        valtype = 'value';
        editls = [ { key:'value', val:'"???"' } ];
    }

    if (tableref.propmap[prop.key] !== undefined) {
        /* Property is already present in table. */
        /*### Update subpanes! Er, unless the type has changed? */
        var propref = tableref.propmap[prop.key];
        var areamap = propref.areamap;
        for (var ix=0; ix<editls.length; ix++) {
            var subpane = editls[ix];
            var subpanel = areamap[subpane.key];
            if (subpane.val)
                subpanel.val(subpane.val);
            else
                subpanel.val('');
            subpanel.trigger('autosize.resize');
        }
    }
    else {
        /* Property is not in table. Add a row. */
        var rowel = $('<tr>', { valign:'top' });
        var cellkeyel = $('<td>');
        var cellvalel = $('<td>');

        rowel.data('key', prop.key);
    
        if (editls.length > 1) {
            /* Put in a blank label to line up with the second column's
               label. */
            var sublabel = $('<div>', { 'class':'BuildPropSublabel' }).text(NBSP);
            cellkeyel.append(sublabel);
        }
        cellkeyel.append($('<span>', { 'class':'BuildPropKey' }).text(prop.key));
        var selectel = $('<select>', { 'class':'BuildPropTypeSelect' });
        for (var ix=0; ix<property_type_selectors.length; ix++) {
            var selector = property_type_selectors[ix];
            selectel.append($('<option>', { value:selector.value }).text(selector.text));
        }
        selectel.prop('value', valtype);
        cellkeyel.append(selectel);

        var areamap = {};
    
        for (var ix=0; ix<editls.length; ix++) {
            var subpane = editls[ix];
            if (subpane.label) {
                var sublabel = $('<div>', { 'class':'BuildPropSublabel' }).text(subpane.label);
                cellvalel.append(sublabel);
            }
            var subpanel = $('<textarea>', { 'class':'BuildPropSubpane', 'rows':'1' });
            /* subpane.val may be undef here */
            if (subpane.val)
                subpanel.val(subpane.val);
            else
                subpanel.val('');
            var boxel = $('<div>', { 'style':'position:relative;' }).append(subpanel);
            /* ### subpanel.autosize() when updating? */
            cellvalel.append(boxel);

            areamap[subpane.key] = subpanel;
            subpanel.data('key', prop.key);
            subpanel.data('subkey', subpane.key);
        }
    
        var buttonsel = $('<div>', { style:'display: none; text-align: right;' });
        var buttonel = $('<input>', { type:'submit', value:'Revert' });
        buttonsel.append(buttonel);
        var buttonel = $('<input>', { type:'submit', value:'Save' });
        buttonsel.append(buttonel);
        cellvalel.append(buttonsel);
    
        rowel.append(cellkeyel);
        rowel.append(cellvalel);
        tableel.append(rowel);

        var propref = {
            key: prop.key, tablekey: tableref.tablekey, valtype: valtype,
            rowel: rowel, buttonsel: buttonsel, areamap: areamap
        };

        tableref.proplist.push(prop.key);
        tableref.propmap[prop.key] = propref;
    }
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
        build_proptable($('#build_loc_properties'), db_props, pagelockey);
    }
    if (pageid == 'world') {
        build_proptable($('#build_world_properties'), db_world_props, '$realm');
        build_proptable($('#build_player_properties'), db_player_props, '$player');
    }
    setup_event_handlers();
    /* Give all the textareas the magic autosizing behavior. */
    $('textarea').autosize();
});
