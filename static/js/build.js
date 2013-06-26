
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
   - val: as handed over by the server
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
    { value:'value', text:'Value' },
    { value:'delete', text:'(Delete)' }
];

var initial_setup_done = false;

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

    initial_setup_done = true;

    /* Give all the textareas the magic autosizing behavior. */
    $('textarea').autosize();
    $('textarea').on('input', evhan_input_textarea);
}

/* Construct the contents of a property table. This is called at page-load
   time.
*/
function build_proptable(tableel, proplist, tablekey) {
    var tableref = tables[tablekey];
    if (tableref === undefined) {
        tableref = { tablekey:tablekey, rootel:tableel,
                         propmap:{}, proplist:[] };
        tables[tablekey] = tableref;
    }

    /* Remove any existing rows. */
    tableel.remove('tr');

    /* Add a "add new" row (which will stick at the bottom) */
    var rowel = $('<tr>');
    var cellel = $('<td>', { colspan:2 });
    var buttonsel = $('<div>', { 'class':'BuildPropButtons' });
    var buttonel = $('<input>', { 'class':'BuildPropButtonLarge', type:'submit', value:'Add New' });
    cellel.append(buttonsel);
    buttonsel.append(buttonel);
    rowel.append(cellel);
    tableel.append(rowel);

    buttonel.on('click', { tablekey:tablekey }, evhan_button_addnew);

    for (var ix=0; ix<proplist.length; ix++) {
        update_prop(tableref, proplist[ix]);
    }
}

/* Update (or add) a row of a property table. The table must exist; the
   row is added if it doesn't exist.

   If nocopy is set, the "original" (revert) value of the property is 
   left unchanged.
*/
function update_prop(tableref, prop, nocopy) {
    if (tableref === undefined) {
        console.log('No table for this property group!');
        return;
    }

    var tableel = tableref.rootel;

    var editls = [];
    var valtype = prop.val.type;
    if (valtype == 'value') {
        editls = [ { key:'value', val:prop.val.value, label:'Value' } ];
    }
    else if (valtype == 'text') {
        editls = [ { key:'text', val:prop.val.text, label:'Text' } ];
    }
    else if (valtype == 'code') {
        editls = [ { key:'text', val:prop.val.text, label:'Code' } ];
    }
    else if (valtype == 'move') {
        editls = [
            { key:'loc', val:prop.val.loc, label:'Destination' },
            { key:'text', val:prop.val.text, label:'(Move message)' },
            { key:'oleave', val:prop.val.oleave, label:'[$name] leaves.' },
            { key:'oarrive', val:prop.val.oarrive, label:'[$name] arrives.' } ];
    }
    else if (valtype == 'event') {
        editls = [ 
            { key:'text', val:prop.val.text, label:'(Message)' },
            { key:'otext', val:prop.val.otext, label:'(Message to other players)' } ];
    }
    else if (valtype == 'delete') {
        /* No subpanes, just the "delete" button */
        editls = [];
    }
    else {
        valtype = 'value';
        editls = [ { key:'value', val:'"???"' } ];
    }

    var propref = tableref.propmap[prop.id];
    if (propref !== undefined && propref.valtype == valtype) {
        /* Property is already present in table, with same type. All we have
           to do is update the subpane contents. */
        if (!nocopy)
            propref.val = prop;
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
        if (!nocopy)
            propref.val = prop;
        propref.keyel.text(prop.key);
        propref.selectel.prop('value', valtype);
        propref.cellvalel.empty();
        propref.valtype = valtype;
        var buildres = build_value_cell(propref.cellvalel, tableref.tablekey, prop.key, prop.id, editls);
        propref.areamap = buildres.areamap;
        propref.buttonsel = buildres.buttonsel;
        propref.warningel = buildres.warningel;
    }
    else {
        /* Property is not in table. Add a row. */
        var rowel = $('<tr>', { valign:'top' });
        var cellkeyel = $('<td>');
        var cellvalel = $('<td>');

        rowel.data('key', prop.key);
    
        var keyel = $('<span>', { 'class':'BuildPropKey' }).text(prop.key);
        cellkeyel.append(keyel);
        var selectel = $('<select>', { 'class':'BuildPropTypeSelect' });
        for (var ix=0; ix<property_type_selectors.length; ix++) {
            var selector = property_type_selectors[ix];
            selectel.append($('<option>', { value:selector.value }).text(selector.text));
        }
        selectel.prop('value', valtype);
        selectel.on('change', { tablekey:tableref.tablekey, id:prop.id }, evhan_prop_type_change);
        cellkeyel.append(selectel);

        var buildres = build_value_cell(cellvalel, tableref.tablekey, prop.key, prop.id, editls);
    
        rowel.append(cellkeyel);
        rowel.append(cellvalel);
        tableel.children().filter(":last").before(rowel);

        var propref = {
            id: prop.id, key: prop.key, val: prop,
            tablekey: tableref.tablekey, valtype: valtype,
            rowel: rowel, cellvalel: cellvalel, buttonsel: buildres.buttonsel,
            warningel: buildres.warningel, selectel: selectel,
            keyel: keyel, areamap: buildres.areamap
        };

        tableref.proplist.push(prop.id);
        tableref.propmap[prop.id] = propref;
    }
}

/* Delete a row of the table, if it exists.
*/
function delete_prop(tableref, prop, nocopy) {
    if (tableref === undefined) {
        console.log('No table for this property group!');
        return;
    }

    var tableel = tableref.rootel;
    var propref = tableref.propmap[prop.id];
    if (propref !== undefined) {
        delete tableref.propmap[prop.id];
        /* Is this really the best way to delete one entry from a JS array? */
        var ix = tableref.proplist.indexOf(prop.id);
        if (ix >= 0)
            tableref.proplist.splice(ix, 1);
        propref.rowel.slideUp(200, function() {
                propref.rowel.remove();
            });
    }
}

/* Construct the contents of a property value cell (the second column
   of the table). The cell must be initially empty.

   Returns an object containing references to some of the constructed
   DOM elements: the row of buttons, the warning line, and the map
   of textareas.
*/
function build_value_cell(cellvalel, tablekey, propkey, propid, editls) {
    var areamap = {};
    
    for (var ix=0; ix<editls.length; ix++) {
        var subpane = editls[ix];
        var subpanel = $('<textarea>', { 'class':'BuildPropSubpane', 'rows':'1' });
        /* subpane.val may be undef here */
        if (subpane.val)
            subpanel.val(subpane.val);
        else
            subpanel.val('');
        if (subpane.label)
            subpanel.prop('placeholder', subpane.label);
        var boxel = $('<div>', { 'style':'position:relative;' }).append(subpanel);
        /* ### subpanel.autosize() when updating? */
        cellvalel.append(boxel);
        
        areamap[subpane.key] = subpanel;
        subpanel.data('tablekey', tablekey);
        subpanel.data('key', propkey);
        subpanel.data('id', propid);
        subpanel.data('subkey', subpane.key);

        if (initial_setup_done) {
            subpanel.autosize();
            subpanel.on('input', evhan_input_textarea);
        }
    }

    var warningel = $('<div>', { 'class':'BuildPropWarning', style:'display: none;' });
    cellvalel.append(warningel);
    
    var buttonsel = $('<div>', { 'class':'BuildPropButtons', style:'display: none;' });
    var buttonel = $('<input>', { type:'submit', value:'Revert' });
    buttonel.on('click', { tablekey:tablekey, id:propid }, evhan_button_revert);
    buttonsel.append(buttonel);
    var buttonel = $('<input>', { type:'submit', value:'Save' });
    buttonel.on('click', { tablekey:tablekey, id:propid }, evhan_button_save);
    buttonsel.append(buttonel);
    cellvalel.append(buttonsel);
    
    return { areamap:areamap, buttonsel:buttonsel, warningel:warningel };
}

/* Make the revert/save buttons appear or disappear on a table row.
   Special case: if dirty is the string 'delete', change the 'save' button
   to say that.
*/
function prop_set_dirty(tableref, propref, dirty) {
    if (dirty) {
        propref.dirty = true;
        propref.rowel.addClass('BuildPropDirty');
        var newlabel = (dirty == 'delete') ? 'Delete' : 'Save';
        propref.buttonsel.children('input').filter(':last').prop('value', newlabel);
        propref.buttonsel.filter(":hidden").slideDown(200);
    }
    else {
        propref.dirty = false;
        propref.rowel.removeClass('BuildPropDirty');
        propref.buttonsel.filter(":visible").slideUp(200);
    }
}

/* Make the red "you screwed up" warning line appear or disappear on
   a table row.
*/
function prop_set_warning(tableref, propref, message) {
    if (message) {
        propref.warningel.text(message);
        propref.warningel.filter(":hidden").slideDown(200);
    }
    else {
        propref.warningel.filter(":visible").slideUp(200, function() {
                propref.warningel.empty();
            });
    }
}

/* Callback invoked whenever the user edits the contents of a textarea.
*/
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

function evhan_button_revert(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var propref = tableref.propmap[id];
    if (!propref) {
        console.log('No such property entry: ' + tablekey + ':' + id);
    }

    update_prop(tableref, propref.val);
    prop_set_dirty(tableref, propref, false);
    prop_set_warning(tableref, propref, null);
}

function evhan_button_save(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var propref = tableref.propmap[id];
    if (!propref) {
        console.log('No such property entry: ' + tablekey + ':' + id);
    }

    /* Turn the subpane entries back into a property value. */
    var valtype = propref.valtype;
    var valobj = { type: propref.valtype };
    jQuery.each(propref.areamap, function(subkey, subpanel) {
        var val = jQuery.trim(subpanel.prop('value'));
        if (val)
            valobj[subkey] = val;
        });
    
    msg = { id:propref.id, key:propref.key, val:JSON.stringify(valobj),
            world:pageworldid,
            _xsrf: xsrf_token };
    if (pageid == 'loc') {
        msg.loc = pagelocid;
    }
    else if (pageid == 'world') {
        msg.loc = tableref.tablekey;
    }

    if (valtype == 'delete') {
        msg.delete = true;
    }

    jQuery.ajax({
            url: '/build/setprop',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                console.log('### ajax success: ' + JSON.stringify(data));
                if (data.error) {
                    prop_set_warning(tableref, propref, data.error);
                    prop_set_dirty(tableref, propref, true);
                    return;
                }
                var tableref = null;
                if (pageid == 'world')
                    tableref = tables[data.loc];
                else if (pageid == 'loc' && pagelocid == data.loc)
                    tableref = tables[pagelockey];
                if (!tableref) {
                    console.log('No such table: ' + data.loc + '!');
                    return;
                }
                if (data.delete) {
                    delete_prop(tableref, data.prop);
                }
                else {
                    update_prop(tableref, data.prop);
                    prop_set_warning(tableref, propref, null);
                    prop_set_dirty(tableref, propref, false);
                }
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
                prop_set_warning(tableref, propref, error);
                prop_set_dirty(tableref, propref, true);
            },
            dataType: 'json'
        });
}

function evhan_button_addnew(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;

    var tableref = tables[tablekey];
    if (!tableref)
        return;

    msg = { world:pageworldid,
            _xsrf: xsrf_token };
    if (pageid == 'loc') {
        msg.loc = pagelocid;
    }
    else if (pageid == 'world') {
        msg.loc = tableref.tablekey;
    }

    jQuery.ajax({
            url: '/build/addprop',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                console.log('### ajax success: ' + JSON.stringify(data));
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                var tableref = null;
                if (pageid == 'world')
                    tableref = tables[data.loc];
                else if (pageid == 'loc' && pagelocid == data.loc)
                    tableref = tables[pagelockey];
                if (!tableref) {
                    console.log('No such table: ' + data.loc + '!');
                    return;
                }
                update_prop(tableref, data.prop);
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_prop_type_change(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var propref = tableref.propmap[id];
    if (!propref) {
        console.log('No such property entry: ' + tablekey + ':' + id);
    }

    var valtype = $(ev.target).prop('value');
    /* Construct an empty property structure of the given type. We
       could get fancy with default values, but we won't. */
    update_prop(tableref, { id:propref.id, key:propref.key, val:{ type:valtype } }, true);
    prop_set_dirty(tableref, propref, (valtype == 'delete' ? 'delete' : true));
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

