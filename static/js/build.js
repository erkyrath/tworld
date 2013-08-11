
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
   - keyel: jQuery ref to the <input> element containing the key name
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
    { value:'panic', text:'Panic' },
    { value:'editstr', text:'EditStr' },
    { value:'portlist', text:'PortList' },
    { value:'datetime', text:'DateTime' },
    { value:'value', text:'Value' },
    { value:'delete', text:'(Delete)' }
];

var initial_setup_done = false;

function setup_event_handlers() {
    var el = $('#build_location_menu');

    if (el.length) {
        var ls = jQuery.map(db_locations, function(loc, index) {
                return { text:loc.name, click:function() { window.location = '/build/loc/' + loc.id; } };
            });
        if (ls.length == 0) {
            ls.push({ text:'(no locations)', enableHook: function(){}, click:function(){} });
        }
        el.contextMenu('popup_menu',
            ls,
            { 
                leftClick: true,
                    position: { my:'left top', at:'left bottom', of:el }
            } );
    }

    initial_setup_done = true;

    /* Give all the textareas the magic autosizing behavior, and also the
       on-edit trigger. (Not <input> elements; those are handled
       case-by-case.) */
    var textareas = $('textarea');
    if (textareas.length) {
        textareas.autosize();
        textareas.on('input', evhan_input_textarea);
    }

    if (pageid == 'world') {
        $('#button_add_new_location').on('click', evhan_button_addlocation);
        $('#button_add_new_portlist').on('click', evhan_button_addportlist);
    }
}

/* Construct the contents of a property table. This is called at page-load
   time.
*/
function build_proptable(tableel, proplist, tablekey, title, readonly) {
    var tableref = tables[tablekey];
    if (tableref === undefined) {
        tableref = { tablekey:tablekey, rootel:tableel, readonly:readonly,
                     propmap:{}, proplist:[] };
        tables[tablekey] = tableref;
    }

    /* Empty out the table. */
    tableel.empty();

    /* Add a colgroup, defining the column widths. */
    tableel.append($('<colgroup><col width="20%"></col><col width="5%"></col><col width="70%"></col></colgroup>'));

    var rowel = $('<tr>');
    var cellel = $('<th>', { colspan:3 });
    cellel.text(title);
    rowel.append(cellel);
    tableel.append(rowel);

    /* Add a "add new" row (which will stick at the bottom) */
    var rowel = $('<tr>');
    var cellel = $('<td>', { colspan:3 });
    rowel.append(cellel);
    tableel.append(rowel);
    /* It is currently the case that only readonly tables are pageable. */
    if (!readonly) {
        var buttonsel = $('<div>', { 'class':'BuildPropButtons' });
        var buttonel = $('<input>', { 'class':'BuildPropButtonLarge', type:'submit', value:'New Property' });
        cellel.append(buttonsel);
        buttonsel.append(buttonel);
        
        buttonel.on('click', { tablekey:tablekey }, evhan_button_addnew);
    }
    else {
        var buttonsel = $('<div>', { 'class':'BuildPropButtons' });
        var buttonel;
        if (pagingprev)
            buttonel = $('<a>', { href:'?page='+(pagingnum-1) });
        else
            buttonel = $('<span>');
        buttonel.text('\u21D0 Previous'); /* left arrow */
        buttonsel.append(buttonel);
        buttonsel.append(' | ');
        if (pagingnext)
            buttonel = $('<a>', { href:'?page='+(pagingnum+1) });
        else
            buttonel = $('<span>');
        buttonel.text('Next Page \u21D2'); /* right arrow */
        buttonsel.append(buttonel);
        cellel.append(buttonsel);
    }

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
    else if (valtype == 'datetime') {
        editls = [ { key:'value', val:prop.val.value, label:'YYYY-MM-DD HH:MM:SS' } ];
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
    else if (valtype == 'panic') {
        editls = [ 
            { key:'text', val:prop.val.text, label:'(Message)' },
            { key:'otext', val:prop.val.otext, label:'(Message to other players)' } ];
    }
    else if (valtype == 'editstr') {
        editls = [ 
            { key:'key', val:prop.val.key, label:'String property' },
            { key:'editaccess', val:prop.val.editaccess, label:'member' },
            { key:'label', val:prop.val.label, label:'(Label)' },
            { key:'text', val:prop.val.text, label:'(Message)' },
            { key:'otext', val:prop.val.otext, label:'(Message to other players)' } ];
    }
    else if (valtype == 'portlist') {
        editls = [ 
            { key:'plistkey', val:prop.val.plistkey, label:'Portlist key' },
            { key:'focus', val:prop.val.focus, label:'false' },
            { key:'readaccess', val:prop.val.readaccess, label:'visitor' },
            { key:'editaccess', val:prop.val.editaccess, label:'member' },
            { key:'text', val:prop.val.text, label:'(Label)' } ];
    }
    else if (valtype == 'delete') {
        /* No subpanes, just the "delete" button */
        editls = [];
    }
    else {
        /* ### This is really not right at all. We should default to the
           *Python* repr() of the typed dict. Which means we need to do
           it on the Python side, obviously. */
        valtype = 'value';
        editls = [ { key:'value', val:JSON.stringify(prop.val) } ];
    }

    var propref = tableref.propmap[prop.id];
    if (propref !== undefined && propref.valtype == valtype) {
        /* Property is already present in table, with same type. All we have
           to do is update the subpane contents. */
        if (!nocopy)
            propref.val = prop;
        propref.keyel.prop('value', prop.key);
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
        propref.keyel.prop('value', prop.key);
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
        var celltypeel = $('<td>');
        var cellvalel = $('<td>');

        rowel.data('key', prop.key);
    
        var keyel = $('<input>', { 'class':'BuildPropKey', autocapitalize:'off' });
        keyel.prop('value', prop.key);
        if (tableref.readonly)
            keyel.prop('readonly', true);
        keyel.data('id', prop.id);
        keyel.data('tablekey', tableref.tablekey);
        keyel.on('input', evhan_input_keyinput);
        cellkeyel.append(keyel);
        var selectel = $('<select>', { 'class':'BuildPropTypeSelect' });
        for (var ix=0; ix<property_type_selectors.length; ix++) {
            var selector = property_type_selectors[ix];
            selectel.append($('<option>', { value:selector.value }).text(selector.text));
        }
        selectel.prop('value', valtype);
        if (tableref.readonly)
            selectel.prop('disabled', true);
        else
            selectel.on('change', { tablekey:tableref.tablekey, id:prop.id }, evhan_prop_type_change);
        celltypeel.append(selectel);

        var buildres = build_value_cell(cellvalel, tableref.tablekey, prop.key, prop.id, editls);
    
        rowel.append(cellkeyel);
        rowel.append(celltypeel);
        rowel.append(cellvalel);
        tableel.find('tr').filter(':last').before(rowel);

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

/* Construct the contents of a property value cell (the third column
   of the table). The cell must be initially empty.

   Returns an object containing references to some of the constructed
   DOM elements: the row of buttons, the warning line, and the map
   of textareas.
*/
function build_value_cell(cellvalel, tablekey, propkey, propid, editls) {
    var areamap = {};
    var arealist = [];
    
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

        arealist.push(subpanel);
    }

    if (tables[tablekey].readonly) {
        for (var ix=0; ix<arealist.length; ix++) {
            var subpanel = arealist[ix];
            subpanel.prop('readonly', true);
        }
    }

    if (initial_setup_done && arealist.length) {
        /* If we added new textareas, we need to give them magic autosizing
           and event handlers. But the autosizing extension doesn't work
           right if the row hasn't been added to the DOM yet. So we defer
           until the event cycle has settled down. */
        defer_func(function() {
                for (var ix=0; ix<arealist.length; ix++) {
                    var subpanel = arealist[ix];
                    subpanel.autosize();
                    subpanel.on('input', evhan_input_textarea);
                }
            });
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
   This is also used for portal tables (despite the name).
*/
function prop_set_dirty(tableref, propref, dirty) {
    if (dirty) {
        propref.dirty = true;
        propref.rowel.addClass('BuildPropDirty');
        var newlabel = (dirty == 'delete') ? 'Delete' : 'Save';
        propref.buttonsel.find('input').filter(':last').prop('value', newlabel);
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
   This is also used for portal tables (despite the name).
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

function build_main_fields() {
    $('#button_addworld_location').on('click', function() {
            $('#button_addworld_confirm').filter(":hidden").slideDown(200);
        });
    $('#button_addworld_cancel').on('click', function() {
            $('#button_addworld_confirm').filter(":visible").slideUp(200);
        });
    $('#button_addworld_addworld').on('click', evhan_button_addworld);
}

function build_location_fields() {
    var cellel = $('#build_loc_name_cell');
    build_geninput_cell(cellel, pagelocname, 'locname', function (val) {
            /* ### Should update the pop-up location menu, too */
            $('#build_location_name').text(val);
        });
   
    var cellel = $('#build_loc_key_cell');
    build_geninput_cell(cellel, pagelockey, 'lockey');

    $('#button_copyportal_location').on('click', function() {
            $('#button_copyportal_confirm').filter(":hidden").slideDown(200);
        });
    $('#button_copyportal_cancel').on('click', function() {
            $('#button_copyportal_confirm').filter(":visible").slideUp(200);
        });
    $('#button_copyportal_copyportal').on('click', evhan_button_copyportal);

    $('#button_delete_location').on('click', function() {
            $('#button_delete_confirm').filter(":hidden").slideDown(200);
        });
    $('#button_delete_cancel').on('click', function() {
            $('#button_delete_confirm').filter(":visible").slideUp(200);
        });
    $('#button_delete_delete').on('click', evhan_button_dellocation);
}

function build_portlist_fields() {
    var cellel = $('#build_plist_key_cell');
    build_geninput_cell(cellel, pageplistkey, 'plistkey');

    $('#button_delete_portlist').on('click', function() {
            $('#button_delete_confirm').filter(":hidden").slideDown(200);
        });
    $('#button_delete_cancel').on('click', function() {
            $('#button_delete_confirm').filter(":visible").slideUp(200);
        });
    $('#button_delete_delete').on('click', evhan_button_delportlist);
}

function build_world_fields() {
    var cellel = $('#build_world_name_cell');
    build_geninput_cell(cellel, pageworldname, 'worldname', function (val) {
            $('#build_world_name').text(val);
        });

    var cellel = $('#build_world_copyable_cell');
    build_geninput_cell(cellel, worldcopyable, 'worldcopyable');

    var cellel = $('#build_world_instancing_cell');
    build_geninput_cell(cellel, worldinstancing, 'worldinstancing');
}

function build_geninput_cell(cellel, origvalue, name, successfunc) {
    cellel.data('origvalue', origvalue);
    cellel.data('success', successfunc);
    cellel.empty();
    var inputel = $('<input>', { 'class':'BuildPropKey', autocapitalize:'off' });
    inputel.prop('value', origvalue);
    inputel.on('input', { cell:cellel }, evhan_input_geninput);
    cellel.append(inputel);

    var warningel = $('<div>', { 'class':'BuildPropWarning', style:'display: none;' });
    cellel.append(warningel);
    
    var buttonsel = $('<div>', { 'class':'BuildPropButtons', style:'display: none;' });
    var buttonel = $('<input>', { type:'submit', value:'Revert' });
    buttonel.on('click', { cell:cellel }, evhan_button_geninput_revert);
    buttonsel.append(buttonel);
    var buttonel = $('<input>', { type:'submit', value:'Save' });
    buttonel.on('click', { cell:cellel, name:name }, evhan_button_geninput_save);
    buttonsel.append(buttonel);
    cellel.append(buttonsel);
}

/* Construct the contents of a property table. This is called at page-load
   time.
*/
function build_portaltable(tableel, portlist, tablekey) {
    var tableref = tables[tablekey];
    if (tableref === undefined) {
        tableref = { tablekey:tablekey, rootel:tableel,
                     portmap:{}, portlist:[] };
        tables[tablekey] = tableref;
    }

    /* Empty out the table. */
    tableel.empty();

    /* Add a colgroup, defining the column widths. */
    tableel.append($('<colgroup><col width="25%"></col><col width="70%"></col></colgroup>'));

    var rowel = $('<tr>');
    var cellel = $('<th>', { colspan:2 });
    cellel.text('Portals');
    rowel.append(cellel);
    tableel.append(rowel);

    /* Add a "add new" row (which will stick at the bottom) */
    var rowel = $('<tr>');
    var cellel = $('<td>', { colspan:3 });
    rowel.append(cellel);
    tableel.append(rowel);
    if (true) {
        var buttonsel = $('<div>', { 'class':'BuildPropButtons' });
        var buttonel = $('<input>', { 'class':'BuildPropButtonLarge', type:'submit', value:'New Portal' });
        cellel.append(buttonsel);
        buttonsel.append(buttonel);
        
        buttonel.on('click', { tablekey:tablekey }, evhan_button_addportal);
    }

    for (var ix=0; ix<portlist.length; ix++) {
        update_portal(tableref, portlist[ix]);
    }
}

function update_portal(tableref, port, nocopy) {
    if (tableref === undefined) {
        console.log('No table for this portal group!');
        return;
    }

    var tableel = tableref.rootel;

    var desc = [];
    desc.push($('<span>').text(port.worldname + ' \u2013 ' + port.locname + ' \u00A0 '));
    if (port.instancing == 'solo') {
        desc.push($('<em>').text('(solo world)'));
    }
    else if (port.instancing == 'shared') {
        desc.push($('<em>').text('(shared world)'));
    }
    else {
        if (port.scid == 'global')
            desc.push($('<em>').text('(player\'s global instance)'));
        else if (port.scid == 'personal')
            desc.push($('<em>').text('(player\'s personal instance)'));
        else if (port.scid == 'same')
            desc.push($('<em>').text('(player\'s current instance)'));
        else {
            if (port.scopetype == 'glob')
                desc.push($('<em>').text('(global)'));
            else if (port.scopetype == 'pers')
                desc.push($('<em>').text('(personal: '+port.scopename+')'));
            else if (port.scopetype == 'grp')
                desc.push($('<em>').text('(group: '+port.scopename+')'));
            else
                desc.push($('<em>').text('(???)'));
        }
    }
    desc.push($('<br>'));
    desc.push($('<em>').text(NBSP + NBSP + '(by ' + port.creatorname + ')'));

    var portref = tableref.portmap[port.id];
    if (portref !== undefined) {
        /* Portal is already present in table. */
        if (!nocopy)
            portref.val = port;
        portref.textel.empty();
        for (var ix=0; ix<desc.length; ix++) {
            portref.textel.append(desc[ix]);
        }
    }
    else {
        /* Portal is not in table. Add a row. */
        var rowel = $('<tr>', { valign:'top' });
        var cellctel = $('<td>');
        var cellvalel = $('<td>');

        var buttonsel = $('<div>', { });
        var buttonel = $('<input>', { type:'submit', value:'World' });
        buttonel.on('click', { tablekey:tableref.tablekey, id:port.id }, evhan_button_portal_set_world);
        buttonsel.append(buttonel);
        var buttonel = $('<input>', { type:'submit', value:'Instance' });
        buttonel.on('click', { tablekey:tableref.tablekey, id:port.id }, evhan_button_portal_set_instance);
        buttonsel.append(buttonel);
        var buttonel = $('<input>', { type:'submit', value:'Delete' });
        buttonel.on('click', { tablekey:tableref.tablekey, id:port.id }, evhan_button_portal_set_delete);
        buttonsel.append(buttonel);
        cellctel.append(buttonsel);

        var buildres = build_portal_cell(cellvalel, tableref.tablekey, port);

        for (var ix=0; ix<desc.length; ix++) {
            buildres.textel.append(desc[ix]);
        }

        rowel.append(cellctel);
        rowel.append(cellvalel);
        tableel.find('tr').filter(':last').before(rowel);

        var portref = {
            id: port.id, val: port,
            tablekey: tableref.tablekey,
            rowel: rowel, cellvalel: cellvalel, buttonsel: buildres.buttonsel,
            controlel: buildres.controlel,
            warningel: buildres.warningel, textel: buildres.textel
        };

        tableref.portlist.push(port.id);
        tableref.portmap[port.id] = portref;
    }
}

/* Construct the contents of a portal value cell (the second column
   of the table). The cell must be initially empty.

   Returns an object containing references to some of the constructed
   DOM elements: the row of buttons, the warning line, the div where the
   description goes.
*/
function build_portal_cell(cellvalel, tablekey, port) {
    var textel = $('<div>');
    cellvalel.append(textel);

    var warningel = $('<div>', { 'class':'BuildPropWarning', style:'display: none;' });
    cellvalel.append(warningel);
    
    var buttonsel = $('<div>', { style:'display: none;' });
    var controlel = $('<div>');
    buttonsel.append(controlel);
    var subbuttonsel = $('<div>', { 'class':'BuildPropButtons' });
    buttonsel.append(subbuttonsel);

    var buttonel = $('<input>', { type:'submit', value:'Revert' });
    buttonel.on('click', { tablekey:tablekey, id:port.id }, evhan_button_portal_revert);
    subbuttonsel.append(buttonel);
    var buttonel = $('<input>', { type:'submit', value:'Save' });
    buttonel.on('click', { tablekey:tablekey, id:port.id }, evhan_button_portal_save);
    subbuttonsel.append(buttonel);
    cellvalel.append(buttonsel);
    
    return { textel:textel, controlel:controlel, 
            buttonsel:buttonsel, warningel:warningel };
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
    if (tableref.readonly)
        return;
    var propref = tableref.propmap[id];
    if (!propref) {
        console.log('No such property entry: ' + tablekey + ':' + id + ':' + subkey);
    }
    if (!propref.dirty) {
        prop_set_dirty(tableref, propref, true);
    }
}

/* Callback invoked whenever the user edits the contents of a (key name)
   input line.
*/
function evhan_input_keyinput(ev) {
    var el = $(ev.target);
    var tablekey = el.data('tablekey');
    var id = el.data('id');

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    if (tableref.readonly)
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
    
    var newkey = jQuery.trim(propref.keyel.prop('value'));
    msg = { id:propref.id, key:newkey, val:JSON.stringify(valobj),
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
                prop_set_warning(tableref, propref, error);
                prop_set_dirty(tableref, propref, true);
            },
            dataType: 'json'
        });
}

function evhan_button_portal_set_world(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var portref = tableref.portmap[id];
    if (!portref) {
        console.log('No such portal entry: ' + tablekey + ':' + id);
    }

    portref.controlel.empty();
    /*####*/

    prop_set_dirty(tableref, portref, true);
}

function evhan_button_portal_set_instance(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var portref = tableref.portmap[id];
    if (!portref) {
        console.log('No such portal entry: ' + tablekey + ':' + id);
    }

    portref.controlel.empty();
    /*####*/

    prop_set_dirty(tableref, portref, true);
}

function evhan_button_portal_set_delete(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var portref = tableref.portmap[id];
    if (!portref) {
        console.log('No such portal entry: ' + tablekey + ':' + id);
    }

    portref.controlel.empty();
    var el = $('<span>', { 'class':'BuildPropWarning' }).text('Delete this portal?');
    portref.controlel.append(el);

    prop_set_dirty(tableref, portref, true);
}

function evhan_button_portal_revert(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var portref = tableref.portmap[id];
    if (!portref) {
        console.log('No such portal entry: ' + tablekey + ':' + id);
    }

    update_portal(tableref, portref.val);
    prop_set_dirty(tableref, portref, false);
    prop_set_warning(tableref, portref, null);
}

function evhan_button_portal_save(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;
    var id = ev.data.id;

    var tableref = tables[tablekey];
    if (!tableref)
        return;
    var portref = tableref.portmap[id];
    if (!portref) {
        console.log('No such portal entry: ' + tablekey + ':' + id);
    }

    /*####*/
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

function evhan_button_addportal(ev) {
    ev.preventDefault();
    var tablekey = ev.data.tablekey;

    var tableref = tables[tablekey];
    if (!tableref)
        return;

    /* No parameters here -- we always create a portal to the start world. */
    msg = { world:pageworldid, plist:pageplistid,
            _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/addport',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                var tableref = tables['$portlist'];
                if (!tableref) {
                    console.log('No such table: ' + '$portlist' + '!');
                    return;
                }
                update_portal(tableref, data.port);
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_button_addlocation(ev) {
    ev.preventDefault();

    msg = { world:pageworldid,
            _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/addloc',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                window.location = '/build/loc/' + data.id;
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_button_dellocation(ev) {
    ev.preventDefault();

    msg = { world:pageworldid, loc:pagelocid,
            _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/delloc',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                window.location = '/build/world/' + pageworldid;
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_button_addportlist(ev) {
    ev.preventDefault();

    msg = { world:pageworldid,
            _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/addportlist',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                window.location = '/build/portlist/' + data.id;
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_button_delportlist(ev) {
    ev.preventDefault();

    msg = { world:pageworldid, plist:pageplistid,
            _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/delportlist',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                window.location = '/build/world/' + pageworldid;
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function evhan_button_addworld(ev) {
    ev.preventDefault();

    msg = { _xsrf: xsrf_token };

    jQuery.ajax({
            url: '/build/addworld',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    console.log('### error: ' + data.error);
                    return;
                }
                window.location = '/build/world/' + data.id;
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
    var newkey = jQuery.trim(propref.keyel.prop('value'));
    /* Construct an empty property structure of the given type. */
    var newprop = { id:propref.id, key:newkey, val:{ type:valtype } };

    /* Make a half-assed effort to clone information from the old property. */
    var oldtext = null;
    if (propref.areamap.text)
        oldtext = propref.areamap.text.prop('value');
    if (!oldtext && propref.areamap.value)
        oldtext = propref.areamap.value.prop('value');
    if (oldtext) {
        if (valtype == 'value' || valtype == 'datetime')
            newprop.val.value = oldtext;
        else
            newprop.val.text = oldtext;
    }

    update_prop(tableref, newprop, true);
    prop_set_dirty(tableref, propref, (valtype == 'delete' ? 'delete' : true));
}

/* Callback for editing a generic field input line. 
*/
function evhan_input_geninput(ev) {
    var cellel = ev.data.cell;
    if (!cellel)
        return;

    if (!cellel.data('dirty'))
        generic_set_dirty(cellel, true);
}

function evhan_button_geninput_revert(ev) {
    var cellel = ev.data.cell;
    if (!cellel)
        return;

    var origval = cellel.data('origvalue');
    cellel.find('input.BuildPropKey').prop('value', origval);
    generic_set_dirty(cellel, false);
    generic_set_warning(cellel, null);
}

function evhan_button_geninput_save(ev) {
    var cellel = ev.data.cell;
    if (!cellel)
        return;
    var name = ev.data.name;
    var newval = cellel.find('input.BuildPropKey').prop('value');
    newval = jQuery.trim(newval);

    var msg = { world:pageworldid,
                name:name, val:newval,
                _xsrf: xsrf_token };
    if (pageid == 'loc') {
        msg.loc = pagelocid;
    }
    if (pageid == 'portlist') {
        msg.plist = pageplistid;
    }

    jQuery.ajax({
            url: '/build/setdata',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    generic_set_warning(cellel, data.error);
                    generic_set_dirty(cellel, true);
                    return;
                }
                cellel.find('input.BuildPropKey').prop('value', data.val);
                cellel.data('origvalue', data.val);
                var successfunc = cellel.data('success');
                if (successfunc)
                    successfunc(data.val);
                generic_set_warning(cellel, null);
                generic_set_dirty(cellel, false);
            },
            error: function(jqxhr, status, error) {
                generic_set_warning(cellel, error);
                generic_set_dirty(cellel, true);
            },
            dataType: 'json'
        });
}

function evhan_button_copyportal(ev) {
    var msg = { world:pageworldid,
                name:'copyportal', val:'dummy',
                _xsrf: xsrf_token };
    if (pageid == 'loc') {
        msg.loc = pagelocid;
    }

    jQuery.ajax({
            url: '/build/setdata',
            type: 'POST',
            data: msg,
            success: function(data, status, jqhxr) {
                if (data.error) {
                    return;
                }
                $('#button_copyportal_confirm').filter(":visible").slideUp(200);
            },
            error: function(jqxhr, status, error) {
                console.log('### ajax failure: ' + status + '; ' + error);
            },
            dataType: 'json'
        });
}

function generic_set_dirty(cellel, dirty) {
    if (dirty) {
        cellel.data('dirty', true);
        cellel.parent().addClass('BuildPropDirty');
        cellel.find('.BuildPropButtons').filter(":hidden").slideDown(200);
    }
    else {
        cellel.data('dirty', false);
        cellel.parent().removeClass('BuildPropDirty');
        cellel.find('.BuildPropButtons').filter(":visible").slideUp(200);
    }
}

function generic_set_warning(cellel, message) {
    var warningel = cellel.find('div.BuildPropWarning');

    if (message) {
        warningel.text(message);
        warningel.filter(":hidden").slideDown(200);
    }
    else {
        warningel.filter(":visible").slideUp(200, function() {
                warningel.empty();
            });
    }
}

/* Run a function (no arguments) "soon". */
function defer_func(func) {
    return window.setTimeout(func, 0.01*1000);
}


/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    /*### install UI prefs to match play page? */
    if (pageid == 'main') {
        build_main_fields();
    }
    if (pageid == 'loc') {
        build_proptable($('#build_loc_properties'), db_props, pagelockey, 'Location properties');
        build_location_fields();
    }
    if (pageid == 'portlist') {
        build_portaltable($('#build_portals'), db_portals, '$portlist');
        build_portlist_fields();
    }
    if (pageid == 'world') {
        build_proptable($('#build_world_properties'), db_world_props, '$realm', 'Realm properties');
        build_proptable($('#build_player_properties'), db_player_props, '$player', 'Player default properties');
        build_world_fields();
    }
    if (pageid == 'trash') {
        build_proptable($('#build_trash_properties'), db_trash_props, '$trash', 'Discarded properties', true);
    }
    setup_event_handlers();
});

