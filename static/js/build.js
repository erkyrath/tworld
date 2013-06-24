
/* Here we store all the context information for editing properties.

   "tables" is plural because we might have more than one property table
   on a page. tables[lockey] is the table for location properties;
   tables['$realm'] is realm-level, tables['$player'] is player defaults.

   A table (tableref) has this structure:
   - tablekey: location key, '$realm', '$player'
   - rootel: jQuery ref to the <table> element
   - proplist: list of prop IDs, in the order displayed
   - propmap: maps prop IDs to prop objects.

   A prop object (propref) has this structure:
   - id: the prop id
   - key: the prop key
   - tablekey: as above
   - valtype: 'text', 'code', 'value', etc
   - rowel: jQuery ref to the <tr> element
   - keyel: jQuery ref to the <span> element containing the key name
   - cellvalel: jQuery ref to the second-col <td> element
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
    if (tableref === undefined) {
        console.log('No table for this property group!');
        return;
    }

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

    var propref = tableref.propmap[prop.id];
    if (propref !== undefined && propref.valtype == valtype) {
        /* Property is already present in table, with same type. All we have
           to do is update the subpane contents. */
        propref.keyel.text(prop.key);
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
    else if (propref !== undefined) {
        /* Property is present in table, but with a different type. We
           need to clean out the second-column cell and rebuild it. */
        propref.keyel.text(prop.key);
        propref.cellvalel.empty();
        propref.valtype = valtype;
        var buildres = build_value_cell(propref.cellvalel, tableref.tablekey, prop.key, prop.id, editls);
        propref.areamap = buildres.areamap;
        propref.buttonsel = buildres.buttonsel;
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
        var keyel = $('<span>', { 'class':'BuildPropKey' }).text(prop.key);
        cellkeyel.append(keyel);
        var selectel = $('<select>', { 'class':'BuildPropTypeSelect' });
        for (var ix=0; ix<property_type_selectors.length; ix++) {
            var selector = property_type_selectors[ix];
            selectel.append($('<option>', { value:selector.value }).text(selector.text));
        }
        selectel.prop('value', valtype);
        cellkeyel.append(selectel);

        var buildres = build_value_cell(cellvalel, tableref.tablekey, prop.key, prop.id, editls);
    
        rowel.append(cellkeyel);
        rowel.append(cellvalel);
        tableel.append(rowel);

        var propref = {
            id: prop.id, key: prop.key, 
            tablekey: tableref.tablekey, valtype: valtype,
            rowel: rowel, cellvalel: cellvalel, buttonsel: buildres.buttonsel,
            keyel: keyel, areamap: buildres.areamap
        };

        tableref.proplist.push(prop.id);
        tableref.propmap[prop.id] = propref;
    }
}

function build_value_cell(cellvalel, tablekey, propkey, propid, editls) {
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
        subpanel.data('tablekey', tablekey);
        subpanel.data('key', propkey);
        subpanel.data('id', propid);
        subpanel.data('subkey', subpane.key);
    }
    
    var buttonsel = $('<div>', { 'class':'BuildPropButtons', style:'display: none;' });
    var buttonel = $('<input>', { type:'submit', value:'Revert' });
    buttonsel.append(buttonel);
    var buttonel = $('<input>', { type:'submit', value:'Save' });
    buttonsel.append(buttonel);
    cellvalel.append(buttonsel);
    
    return { areamap:areamap, buttonsel:buttonsel };
}

function prop_set_dirty(tableref, propref, dirty) {
    console.log('### setting prop ' + propref.key + ' to dirty=' + dirty);
    if (dirty) {
        propref.dirty = true;
        propref.rowel.addClass('BuildPropDirty');
        propref.buttonsel.slideDown(200);
    }
    else {
        propref.dirty = false;
        propref.rowel.removeClass('BuildPropDirty');
        propref.buttonsel.slideUp(200);
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

    /* Give all the textareas the magic autosizing behavior. */
    $('textarea').autosize();
    $('textarea').on('input', evhan_input_textarea);
}

function evhan_input_textarea(ev) {
    var el = $(ev.target);
    var tablekey = el.data('tablekey');
    var id = el.data('id');
    var subkey = el.data('subkey');

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var propref = tableref.propmap[id];
    if (!propref) {
        console.log('No such property entry: ' + tablekey + ':' + id + ':' + subkey);
    }
    if (!propref.dirty) {
        prop_set_dirty(tableref, propref, true);
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
});

