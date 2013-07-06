
var websocket = null;
var connected = false;
var everconnected = false;

/* Default values for all the UI preferences. These will be overridden by
   player preferences. */
var uiprefs = {
    toolseg_min_prefs: true,
    leftright_percent: 75,
    updown_percent: 70,
    font_size: 100,
    line_height: 135,
    smooth_scroll: true
};

/* When there are more than 80 lines in the event pane, chop it down to
   the last 60. */
var EVENT_TRIM_LIMIT = 80;
var EVENT_TRIM_KEEP = 60;

var KEY_RETURN = 13;
var KEY_UP = 38;
var KEY_DOWN = 40;

var NBSP = '\u00A0';

/* The db_uiprefs object contains the player preferences. They're written
   directly into the play.html template by the web server. Copy them
   over the defaults, where present.
*/
function collate_uiprefs() {
    for (var key in db_uiprefs) {
        uiprefs[key] = db_uiprefs[key];
    }
}

/* Construct the DOM for the page.
*/
function build_page_structure() {
    /* Clear out the body from the play.html template. */
    $('#submain').empty();

    var topcol = $('<div>', { id: 'topcol' });
    var leftcol = $('<div>', { id: 'leftcol' });
    var localepane = $('<div>', { id: 'localepane' });
    var rightcol = $('<div>', { id: 'rightcol' });
    var bottomcol = $('<div>', { id: 'bottomcol' });
    var eventpane = $('<div>', { id: 'eventpane' });
    var eventboxpane = $('<div>', { id: 'eventboxpane' });

    localepane.append($('<div>', { id: 'localepane_locale' }));
    localepane.append($('<div>', { id: 'localepane_populace' }));

    var tooloutline = $('<div>', { 'class': 'ToolOutline' });
    var toolheader = $('<div>', { 'class': 'ToolTitleBar' });
    tooloutline.append(toolheader);
    toolpane_build_segment('plist', true);
    tooloutline.append(toolsegments['plist'].segel);
    toolpane_build_segment('prefs', false);
    tooloutline.append(toolsegments['prefs'].segel);
    tooloutline.append($('<div>', { 'class': 'ToolFooter' }));

    toolheader.append($('<h2>', { id: 'tool_title_title', 'class': 'ToolTitle' }));
    toolheader.append($('<div>', { id: 'tool_title_scope', 'class': 'ToolData' }));
    toolheader.append($('<h3>', { id: 'tool_title_creator', 'class': 'ToolTitle' }));
    rightcol.append(tooloutline);

    var inputline = $('<div>', { 'class': 'Input' });
    var inputprompt = $('<div>', { 'class': 'InputPrompt' });
    var inputframe = $('<div>', { 'class': 'InputFrame' });

    inputprompt.text('>');
    inputframe.append($('<input>', { id: 'eventinput', type: 'text', maxlength: '256' } ));
    inputline.append(inputprompt);
    inputline.append(inputframe);

    topcol.append(leftcol);
    leftcol.append(localepane);
    topcol.append(rightcol);
    bottomcol.append($('<div>', { id: 'bottomcol_topedge' }));
    bottomcol.append(eventboxpane);
    eventboxpane.append(eventpane);
    eventpane.append(inputline);

    /* Add the top-level, fully-constructed structures to the DOM last. More
       efficient this way. */
    $('#submain').append(topcol);
    $('#submain').append(bottomcol);

    toolpane_set_world(localize('label.in_transition'), NBSP, '...');

    /* Apply the current ui layout preferences. */
    $('#topcol').css({ height: uiprefs.updown_percent+'%' });
    $('#bottomcol').css({ height: (100-uiprefs.updown_percent)+'%' });
    $('#leftcol').css({ width: uiprefs.leftright_percent+'%' });
    $('#rightcol').css({ width: (100-uiprefs.leftright_percent)+'%' });
    var val = uiprefs.font_size / 100.0;
    $('#main').css('font-size', val+'em');
    val = uiprefs.line_height / 100.0;
    $('#submain').css('line-height', val+'em');
}

function build_focuspane(contentls)
{
    var focuspane = $('<div>', { class: 'FocusPane FocusPaneAnimating',
                                 style: 'display:none;' });

    var focusoutline = $('<div>', { 'class': 'FocusOutline' });
    var focuscornercontrol = $('<div class="FocusCornerControl"><a href="#">Close</a></div>');
    focusoutline.append(focuscornercontrol);
    focusoutline.append($('<div>', { 'class': 'InvisibleAbovePara' }));
    for (var ix=0; ix<contentls.length; ix++) {
        focusoutline.append(contentls[ix]);
    }
    focusoutline.append($('<div>', { 'class': 'InvisibleBelowPara' }));
    focuspane.append(focusoutline);

    /* ### make this close control look and act nicer. */
    focuscornercontrol.on('click', evhan_click_dropfocus);

    return focuspane;
}

function setup_event_handlers() {
    $(document).on('keypress', evhan_doc_keypress);

    var inputel = $('#eventinput');
    inputel.on('keypress', evhan_input_keypress);
    inputel.on('keydown', evhan_input_keydown);
    
    $('#leftcol').resizable( { handles:'e', containment:'parent', 
          distance: 4,
          resize:handle_leftright_resize, stop:handle_leftright_doneresize } );
    $('#topcol').resizable( { handles:'s', containment:'parent',
          distance: 4,
          resize:handle_updown_resize, stop:handle_updown_doneresize } );
    
    $('div.ui-resizable-handle').append('<div class="ResizingThumb">');

    /* The controls in the prefs pane... */

    var seg = toolsegments['prefs'];

    seg.fontsizeslider.slider({
            value: uiprefs.font_size, min: 80, max: 120, step: 5,
            stop: function(ev, ui) {
                var val = ui.value / 100.0;
                $('#main').css('font-size', val+'em');
                uiprefs.font_size = Math.round(ui.value);
                note_uipref_changed('font_size');
            }
        });

    seg.lineheightslider.slider({
            value: uiprefs.line_height, min: 120, max: 150, step: 5,
            stop: function(ev, ui) {
                var val = ui.value / 100.0;
                $('#submain').css('line-height', val+'em');
                uiprefs.line_height = Math.round(ui.value);
                note_uipref_changed('line_height');
            }
        });

    seg.smoothscrollbox.prop('checked', uiprefs.smooth_scroll);
    seg.smoothscrollbox.on('change', function(ev) {
            var seg = toolsegments['prefs'];
            if (seg.smoothscrollbox.prop('checked'))
                uiprefs.smooth_scroll = true;
            else
                uiprefs.smooth_scroll = false;
            note_uipref_changed('smooth_scroll');
        });

}

function open_websocket() {
    try {
        var url = 'ws://' + window.location.host + '/websocket';
        websocket = new WebSocket(url);
    }
    catch (ex) {
        eventpane_add('Unable to open websocket: ' + ex, 'EventError');
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

    var localeel = $('#localepane_locale');
    localeel.empty();
    localeel.append(el);

    $('#localepane_populace').empty();
    focuspane_clear();
}

function toolpane_set_world(world, scope, creator) {
    $('#tool_title_title').text(world);
    $('#tool_title_scope').text(scope);
    $('#tool_title_creator').text(creator);
}

/* Contains a map of all segments currently in the tool column.
   (Minimized ones count. The header bar doesn't count.)
*/
var toolsegments = {};

/* Create a segment, but do not add it to the document. The caller must
   do that, either directly or by calling toolpane_add_segment().
*/
function toolpane_build_segment(key, hasmenu) {
    if (toolsegments[key]) {
        console.log('Tool column already has segment: ' + key);
        return;
    }

    var seg = { key:key };
    toolsegments[key] = seg;

    var isclosed = uiprefs['toolseg_min_'+key];

    /* Build the DOM elements. */
    var segel = $('<div>', {'class':'ToolSegment'});
    var leftbutel = $('<div>', {'class':'ToolControl ToolControlLeft',
                                'title':'Open/close this section'});
    if (isclosed)
        leftbutel.text('\u25B8'); /* right pointer */
    else
        leftbutel.text('\u25BE'); /* down pointer */
    segel.append(leftbutel);
    var rightbutel =  $('<div>', {'class':'ToolControl ToolControlRight',
                                  'title':'Menu for this section'});
    rightbutel.text('\u25C6'); /* diamond */
    if (!hasmenu)
        rightbutel.addClass('ToolControlDimmed');
    segel.append(rightbutel);
    var titleel = $('<h3>', {'class':'ToolTitle'});
    titleel.text('-');
    segel.append(titleel);
    var bodyel = $('<div>');
    if (isclosed)
        bodyel.css({'display':'none'});
    segel.append(bodyel);

    seg.segel = segel;
    seg.titleel = titleel;
    seg.bodyel = bodyel;
    seg.leftbutel = leftbutel;
    seg.rightbutel = rightbutel;

    if (key == 'prefs')
        toolpane_fill_pane_prefs(seg);
    else if (key == 'plist')
        toolpane_fill_pane_plist(seg);
    else if (key == 'portal')
        toolpane_fill_pane_portal(seg);
    else
        console.log('Unrecognized toolpane segment: ' + key);

    leftbutel.on('click', {key:key}, toolpane_toggle_min);

    return seg;
}

function toolpane_add_segment(key, aftersegkey) {
    var seg = toolsegments[key];
    var afterseg = toolsegments[aftersegkey];

    if (!seg)
        return;

    seg.segel.css({display:'none'});
    seg.leftbutel.css({display:'none'});
    seg.rightbutel.css({display:'none'});

    if (afterseg) {
        afterseg.segel.after(seg.segel);
    }
    else {
        $('#rightcol .ToolFooter').before(seg.segel);
    }

    seg.segel.slideDown(200, function() {
            /* Necessary because the absolute buttons don't get clipped by the
               segment height. */
            seg.leftbutel.css({display:''});
            seg.rightbutel.css({display:''});            
        });
}

function toolpane_remove_segment(key) {
    var seg = toolsegments[key];

    if (!seg)
        return;

    var segel = seg.segel;
    segel.slideUp(200, function() { segel.remove(); });

    /* Necessary because the absolute buttons don't get clipped by the
       segment height. */
    seg.leftbutel.css({display:'none'});
    seg.rightbutel.css({display:'none'});

    toolsegments[key] = null;
}

function toolpane_toggle_min(ev) {
    ev.preventDefault();
    /*### end_editing(); */

    var key = ev.data.key;
    var prefkey = 'toolseg_min_'+key;
    var seg = toolsegments[key];

    if (uiprefs[prefkey]) {
        /* Open up */
        if (seg.openhook)
            seg.openhook(seg);
        uiprefs[prefkey] = false;
        seg.bodyel.slideDown(200);
        seg.leftbutel.text('\u25BE'); /* down pointer */
    }
    else {
        /* Minimize */
        uiprefs[prefkey] = true;
        seg.bodyel.slideUp(200);
        seg.leftbutel.text('\u25B8'); /* right pointer */
    }
    note_uipref_changed(prefkey);
}


function toolpane_fill_pane_prefs(seg) {
    seg.titleel.text(localize('client.tool.title.preferences'));

    var listel = $('<ul>', {'class':'ToolList'});
    seg.bodyel.append(listel);

    var el = $('<li>').text('Text Size');
    listel.append(el);
    el.append($('<br>'));
    var fontsizeslider = $('<div>');
    el.append(fontsizeslider);
    seg.fontsizeslider = fontsizeslider;

    el = $('<li>').text('Line Spacing');
    listel.append(el);
    el.append($('<br>'));
    var lineheightslider = $('<div>');
    el.append(lineheightslider);
    seg.lineheightslider = lineheightslider;

    el = $('<li>');
    listel.append(el);
    el.append($('<label>').text('Smooth Scrolling'));
    var smoothscrollbox = $('<input>', {'class':'CheckboxRight', 'type':'checkbox'});
    el.append(smoothscrollbox);
    seg.smoothscrollbox = smoothscrollbox;
}

function toolpane_fill_pane_plist(seg) {
    seg.titleel.text(localize('client.tool.title.portals'));

    var listel = $('<ul>', {'class':'ToolList'});
    seg.listel = listel;
    seg.bodyel.append(listel);

    seg.map = {}; /* maps portid to portal object */
    seg.list = []; /* portals in listpos order */
    seg.selection = null;

    toolpane_plist_update();

    /* Clear selection when opening the segment. */
    seg.openhook = function(seg) { toolpane_plist_select(null); };

    /* Click on the segment title to clear selection. */
    seg.titleel.on('click', seg.openhook);

    seg.rightbutel.contextMenu('popup_menu', 
        [
            { text:localize('client.tool.menu.return_to_start'),
                    click: function() {
                    websocket_send_json({ cmd:'portstart' });
                } },
            { text:localize('client.tool.menu.delete_own_portal'),
                    enableHook: function() { return toolsegments['plist'].selection; },
                    click: function() {
                    var seg = toolsegments['plist'];
                    var portal = seg.map[seg.selection];
                    if (portal) {
                        websocket_send_json({ cmd:'deleteownportal', portid:portal.portid });
                    }
                } },
            { text:localize('client.tool.menu.set_panic_portal'),
                    enableHook: function() { return toolsegments['plist'].selection; },
                    click: function() {
                    var seg = toolsegments['plist'];
                    var portal = seg.map[seg.selection];
                    if (portal) {
                        websocket_send_json({ cmd:'setpreferredportal', portid:portal.portid });
                    }
                } }
         ],
        { 
            leftClick: true,
            position: { my:'right top', at:'right bottom', of:seg.rightbutel }
        } );

}

/* Rebuild the contents of the plist tool segment. The seg.list and seg.map
   have already been filled in. 
*/
function toolpane_plist_update() {
    var seg = toolsegments['plist'];
    var el;

    seg.listel.empty();

    if (!seg.list.length) {
        el = $('<li>', {'class':'ToolListDimmed'}).text('(empty)');
        seg.listel.append(el);
        seg.selection = null;
        return;
    }

    for (var ix=0; ix<seg.list.length; ix++) {
        var portal = seg.list[ix];

        el = $('<li>', {'class':'ToolListButtonish'});
        el.append($('<span>').text(portal.world));
        el.append(' \u2013 '); /* en-dash */
        el.append($('<span>').text(portal.location));
        el.append(' ');
        el.append($('<span>', {'class':'ToolGloss'}).text('('+portal.scope+')'));

        /* Click on entry to select. */
        el.on('click', {portid:portal.portid}, function(ev) {
                ev.preventDefault();
                toolpane_plist_select(ev.data.portid, true);
            } );

        portal.el = el;
        el.data('portid', portal.portid);
        seg.listel.append(el);
    }

    if (seg.selection) {
        var portal = seg.map[seg.selection];
        if (portal) {
            portal.el.addClass('ToolListSelected');
        }
    }
    else {
        seg.selection = null;
    }
}

function toolpane_plist_select(portid, useasfocus) {
    var seg = toolsegments['plist'];
    
    var portal = seg.map[seg.selection];
    if (portal) {
        portal.el.removeClass('ToolListSelected');
    }
    seg.selection = portid;
    portal = seg.map[seg.selection];
    if (!portal) {
        seg.selection = null;
        if (focuspane_current_special_plist_editable()) {
            plistedit_update_portal_selection();
        }
        return;
    }

    portal.el.addClass('ToolListSelected');

    if (focuspane_current_special_plist_editable()) {
        var editel = $('.FocusPane .FocusPlistEdit');
        if (editel.data('visible')) {
            plistedit_update_portal_selection();
            return;
        }
    }

    if (useasfocus) {
        websocket_send_json({ cmd:'plistselect', portid:portid });
    }
}

/* This is called every time the focus changes. It posts, removes, or updates
   the "details on this portal" tool segment.
*/
function toolpane_portal_addremove() {
    var portal = focuspane_current_special_portal();
    if (!portal) {
        /* Remove if necessary. */
        if (toolsegments['portal'])
            toolpane_remove_segment('portal');
        return;
    }

    var seg = toolsegments['portal'];
    if (!seg) {
        /* Make sure it appears open -- but don't bother notifying the
           server. */
        uiprefs['toolseg_min_portal'] = false;
        seg = toolpane_build_segment('portal', false);
        toolpane_add_segment('portal', 'plist');
    }
    else {
        toolpane_portal_update();
    }
}

function toolpane_fill_pane_portal(seg) {
    seg.titleel.text(localize('client.tool.title.this_portal'));

    var listel = $('<ul>', {'class':'ToolList'});
    seg.bodyel.append(listel);

    var el = $('<li>');
    listel.append(el);
    el.append($('<div>', {'class':'ToolLabelRight'}).text(localize('misc.world')));
    var worldel = $('<span>').text('-');
    el.append(worldel);

    el = $('<li>');
    listel.append(el);
    el.append($('<div>', {'class':'ToolLabelRight'}).text(localize('misc.location')));
    var locel = $('<span>').text('-');
    el.append(locel);

    el = $('<li>');
    listel.append(el);
    el.append($('<div>', {'class':'ToolLabelRight'}).text(localize('misc.instance')));
    var scopeel = $('<span>').text('-');
    el.append(scopeel);

    el = $('<li>');
    listel.append(el);
    el.append($('<div>', {'class':'ToolLabelRight'}).text(localize('misc.creator')));
    var creatorel = $('<span>').text('-');
    el.append(creatorel);

    listel = $('<ul>', {'class':'ToolList'});
    seg.bodyel.append(listel);

    var noflexel = $('<li>', {'class':'StyleEmph'});
    listel.append(noflexel);
    var flexel =  $('<li>', {'class':'StyleEmph'}).text(localize('client.label.flexible'));
    flexel.append(' ');
    var flexselectel = $('<select>', {'class':'FocusSelect'});
    flexel.append(flexselectel);
    listel.append(flexel);

    var copyel = $('<li>');
    el = $('<a>', {href:'#'}).text(localize('client.label.copy_portal'));
    copyel.append(el);
    listel.append(copyel);
    var nocopyel = $('<li>', {'class':'StyleEmph'}).text(localize('client.label.not_copyable'));
    listel.append(nocopyel);

    copyel.on('click', function(ev) {
            ev.preventDefault();
            var portal = focuspane_current_special_portal();
            if (portal) {
                var msg = { cmd:'action', action:portal.copyable };
                if (toolsegments['portal']) {
                    var scid = toolsegments['portal'].flexselectel.prop('value');
                    if (scid != portal.scid) 
                        msg.scid = scid;
                }
                websocket_send_json(msg);
            }
        });

    seg.worldel = worldel;
    seg.scopeel = scopeel;
    seg.locel = locel;
    seg.creatorel = creatorel;
    seg.copyel = copyel;
    seg.nocopyel = nocopyel;
    seg.flexel = flexel;
    seg.noflexel = noflexel;
    seg.flexselectel = flexselectel;

    toolpane_portal_update();
}

function toolpane_portal_update() {
    var seg = toolsegments['portal'];

    var portal = focuspane_current_special_portal();
    if (!portal) {
        seg.worldel.text('-');
        seg.scopeel.text('-');
        seg.locel.text('-');
        seg.creatorel.text('-');
        return;
    }

    seg.worldel.text(portal.world);
    seg.scopeel.text(portal.scope);
    seg.locel.text(portal.location);
    seg.creatorel.text(portal.creator);
    if (portal.copyable) {
        seg.copyel.show();
        seg.nocopyel.hide();
    }
    else {
        seg.nocopyel.show();
        seg.copyel.hide();
    }
    if (portal.instancing == 'standard') {
        seg.flexselectel.empty();
        if (availscopemap[portal.scid] === undefined) {
            var optel = $('<option>', { value:portal.scid }).text('*Original');
            seg.flexselectel.append(optel);
        }
        for (var ix=0; ix<availscopelist.length; ix++) {
            scope = availscopelist[ix];
            var optel = $('<option>', { value:scope.id }).text(scope.name);
            if (scope.id == portal.scid)
                optel.prepend('*');
            seg.flexselectel.append(optel);
        }
        seg.flexselectel.prop('value', portal.scid);
        seg.flexel.show();
        seg.noflexel.hide();
    }
    else {
        if (portal.instancing == 'solo')
            seg.noflexel.text(localize('client.label.only_solo'));
        else
            seg.noflexel.text(localize('client.label.only_shared'));
        seg.noflexel.show();
        seg.flexel.hide();
    }
}

function localepane_set_locale(desc, title) {
    var localeel = $('#localepane_locale');
    localeel.empty();

    if (title) {
        var titleel = $('<h2>');
        titleel.text(title);
        localeel.append(titleel);
    }

    var contentls;
    try {
        contentls = parse_description(desc);
    }
    catch (ex) {
        var el = $('<p>');
        el.text('[Error rendering description: ' + ex + ']');
        contentls = [ el ];
    }
    for (var ix=0; ix<contentls.length; ix++) {
        localeel.append(contentls[ix]);
    }
}

function localepane_set_populace(desc) {
    var localeel = $('#localepane_populace');
    localeel.empty();

    if (!desc)
        return;

    var contentls;
    try {
        contentls = parse_description(desc);
    }
    catch (ex) {
        var el = $('<p>');
        el.text('[Error rendering description: ' + ex + ']');
        contentls = [ el ];
    }
    for (var ix=0; ix<contentls.length; ix++) {
        localeel.append(contentls[ix]);
    }
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

function focuspane_clear()
{
    /* If any old panes are in the process of sliding up or down, we
       kill them unceremoniously. */
    var oldel = $('.FocusPaneAnimating');
    if (oldel.length) {
        oldel.remove();
    }

    /* If an old pane exists, slide it out. (The call is "slideUp", even
       though the motion will be downwards. jQuery assumes everything is
       anchored at the top, but we are anchored at the bottom.) */
    var el = $('.FocusPane');
    if (el.length) {
        el.addClass('FocusPaneAnimating');
        el.slideUp(200, function() { el.remove(); });
    }
}

function focuspane_set(desc, extrals)
{
    var contentls;
    try {
        contentls = parse_description(desc);
    }
    catch (ex) {
        var el = $('<p>');
        el.text('[Error rendering description: ' + ex + ']');
        contentls = [ el ];
    }

    if (extrals) {
        /* Append to end of contentls. */
        for (var ix=0; ix<extrals.length; ix++)
            contentls.push(extrals[ix]);
    }

    /* Clear out old panes and slide in the new one. (It will have the
       'FocusPaneAnimating' class until it finishes sliding.) */

    focuspane_clear();

    var newpane = build_focuspane(contentls);
    $('#leftcol').append(newpane);
    newpane.slideDown(200, function() { newpane.removeClass('FocusPaneAnimating'); } );
}

var focuspane_special_val = [];
var focuspane_special_editplist = null;

function focuspane_set_special(ls) {
    /* ### This seriously neglects dependencies. */

    var type = '???';
    try {
        type = ls[0];
        focuspane_special_val = ls;
        focuspane_special_editplist = null;
        if (type == 'selfdesc') {
            /* ['selfdesc', name, pronoun, desc, extratext] */
            var extrals = selfdesc_build_controls();
            focuspane_set(ls[4], extrals);
            $('.FormSelfDescPronoun').prop('value', ls[2]);
            selfdesc_update_labels();
            $('.FormSelfDescPronoun').on('change', selfdesc_pronoun_changed);
            /* Accept edits on enter, or if the focus leaves the textarea. */
            $('.FormSelfDescDesc').on('blur', selfdesc_desc_blur);
            $('.FormSelfDescDesc').on('keypress', function(ev) {
                    if (ev.which == KEY_RETURN) {
                        ev.preventDefault();
                        selfdesc_desc_blur();
                    }
                });
            return;
        }
        if (type == 'editstr') {
            /* ['editstr', key, value, extratext] */
            var extrals = editstr_build_controls();
            focuspane_set(ls[3], extrals);
            $('.FormEditStrValue').on('blur', editstr_value_blur);
            $('.FormEditStrValue').on('keypress', function(ev) {
                    if (ev.which == KEY_RETURN) {
                        ev.preventDefault();
                        editstr_value_blur();
                    }
                });
            return;
        }
        if (type == 'portal') {
            var target = ls[1];
            var portalobj = ls[2];
            var backtarget = ls[3];
            var extratext = ls[4];
            /* Note that extratext, if present, may be a full-fledged
               description. */
            var extrals = [];
            if (backtarget) {
                var ael = $('<a>', {href:'#'+backtarget});
                ael.text(localize('client.label.back_to_plist'));
                ael.on('click', {target:backtarget}, evhan_click_action);
                var el = $('<p>');
                el.append(ael);
                extrals.push(el);
            }
            var el = $('<p>');
            el.text(portalobj.view);
            extrals.push(el);
            var ael = $('<a>', {href:'#'+target});
            ael.text(localize('client.label.enter_portal'));
            ael.on('click', {target:target, scid:portalobj.scid}, function(ev) {
                    ev.preventDefault();
                    var msg = { cmd:'action', action:ev.data.target };
                    if (toolsegments['portal']) {
                        var scid = toolsegments['portal'].flexselectel.prop('value');
                        if (scid != ev.data.scid) 
                            msg.scid = scid;
                    }
                    websocket_send_json(msg);
                });
            el = $('<p>');
            el.append(ael);
            extrals.push(el);
            focuspane_set(extratext, extrals);
            return;
        }
        if (type == 'portlist') {
            var portlist = ls[1];
            var extratext = ls[2];
            var editable = ls[3];
            /* Note that extratext, if present, may be a full-fledged
               description. */
            var extrals = [];
            if (editable) {
                focuspane_special_editplist = $('<div>');
                extrals.push(focuspane_special_editplist);

                var buttonel = $('<input>', { 'class':'FocusButtonLarge FocusPlistEditButton', type:'submit', value:localize('client.button.edit_collection') });
                buttonel.on('click', function(ev) { ev.preventDefault(); plistedit_toggle_edit(); })
                var barel = $('<div>', {'class':'FocusButtonBar'});
                barel.append(buttonel);
                focuspane_special_editplist.append(barel);
                var el = $('<div>', {'class':'FocusPlistEdit', 'style':'display:none;'});
                var labelel = $('<div>', {'class':'FocusPlistPortal'}).text('--');
                el.append(labelel);
                var buttonel = $('<input>', { 'class':'FocusPlistAddButton', type:'submit', value:localize('client.button.add_portal') });
                buttonel.on('click', function(ev) { ev.preventDefault(); plistedit_add_portal(); })
                var barel = $('<div>', {'class':'FocusButtonBar'});
                barel.append(buttonel);
                el.append(barel);
                focuspane_special_editplist.append(el);
                plistedit_update_portal_selection();
            }
            if (!portlist.length) {
                var el = $('<p>').text(localize('client.label.plist_is_empty'));
                extrals.push(el);
            }
            else {
                var el = $('<ul>', {'class':'FocusPlistList'});
                extrals.push(el);
                for (var ix=0; ix<portlist.length; ix++) {
                    var portal = portlist[ix];
                    var lel = $('<li>');
                    if (editable) {
                        var delbutton = $('<div>', {'class':'FocusListDelButton ToolControl', style:'display:none;'}).text('\u00D7');
                        lel.append(delbutton);
                        lel.append(' ');
                    }
                    var ael = $('<a>', {href:'#'+portal.target});
                    ael.text(portal.world);
                    ael.on('click', {target:portal.target}, evhan_click_action);
                    lel.append(ael);
                    lel.append(' ' + NBSP + ' ');
                    var spel = $('<span>', {'class':'StyleEmph'});
                    spel.text(localize('client.label.created_by_paren').replace('%s', portal.creator));
                    lel.append(spel);
                    el.append(lel);
                }
            }
            focuspane_set(extratext, extrals);
            return;
        }
        focuspane_set('### ' + type + ': ' + ls);
    }
    catch (ex) {
        focuspane_special_val = [];
        focuspane_special_editplist = null;
        focuspane_set('[Error creating special focus ' + type + ': ' + ex + ']');
    }
}

/* Returns the portal object that focus is set to, if any; otherwise null.
 */
function focuspane_current_special_portal() {
    var portal = null;
    if (focuspane_special_val && focuspane_special_val[0] == 'portal') {
        portal = focuspane_special_val[2];
    }
    return portal;
}

/* Returns the edit action key, if the focus is set to an editable portlist.
   Otherwise returns null.
 */
function focuspane_current_special_plist_editable() {
    if (focuspane_special_val && focuspane_special_val[0] == 'portlist') {
        if (focuspane_special_val[3])
            return focuspane_special_val[3];
    }
    return false;
}

function plistedit_toggle_edit() {
    var editkey = focuspane_current_special_plist_editable();
    if (!editkey)
        return;
    var editel = $('.FocusPane .FocusPlistEdit');
    if (!editel)
        return;

    if (!editel.data('visible')) {
        $('.FocusPlistEditButton').prop('value', localize('client.button.done_editing'));
        editel.data('visible', true);
        editel.slideDown(200);
        $('.FocusListDelButton').show(200);
        plistedit_update_portal_selection();
    }
    else {
        $('.FocusPlistEditButton').prop('value', localize('client.button.edit_collection'));
        editel.data('visible', false);
        editel.slideUp(200);
        $('.FocusListDelButton').hide(200);
    }
}

function plistedit_add_portal() {
    var editkey = focuspane_current_special_plist_editable();
    if (!editkey)
        return;
    var editel = $('.FocusPane .FocusPlistEdit');
    if (!editel)
        return;

    if (!editel.data('visible')) 
        return;

    var seg = toolsegments['plist'];
    var portal = seg.map[seg.selection];
    if (!portal) 
        return;
    
    websocket_send_json({
        cmd:'action', action:editkey,
        edit:'add', portid:portal.portid});
}

function plistedit_update_portal_selection() {
    var editkey = focuspane_current_special_plist_editable();
    if (!editkey)
        return;
    var editel = $('.FocusPane .FocusPlistEdit');
    if (!editel)
        return;

    var el = editel.find('.FocusPlistPortal');
    if (!el)
        return;
    
    var seg = toolsegments['plist'];
    var portal = seg.map[seg.selection];
    if (!portal) {
        el.text(localize('client.label.select_portal_to_add'));
        $('.FocusPlistAddButton').prop('disabled', true);
    }
    else {
        el.text(portal.world + ' \u2013 ' + portal.location + ' (' + portal.scope + ')');
        $('.FocusPlistAddButton').prop('disabled', false);
    }

}

function selfdesc_build_controls() {
    /* ['selfdesc', name, pronoun, desc, extratext] */
    var extrals = [];
    var el, divel, optel;

    divel = $('<div>', { 'class':'FocusSection' });
    extrals.push(divel);
    el = $('<span>').text('You see...');
    divel.append(el);
    el = $('<br>');
    divel.append(el);
    el = $('<textarea>', { 'class':'FormSelfDescDesc FocusInput', rows:2,
                           autocapitalize:'off', autofocus:'autofocus',
                           name:'desc' });
    el.text(focuspane_special_val[3]);
    divel.append(el);

    divel = $('<div>', { 'class':'FocusSection' });
    extrals.push(divel);
    el = $('<span>').text('Your pronouns: ');
    divel.append(el);
    el = $('<select>', { 'class':'FormSelfDescPronoun FocusSelect', name:'select' });
    divel.append(el);
    optel = $('<option>', { value:'he' }).text('He, his');
    el.append(optel);
    optel = $('<option>', { value:'she' }).text('She, her');
    el.append(optel);
    optel = $('<option>', { value:'it' }).text('It, its');
    el.append(optel);
    optel = $('<option>', { value:'they' }).text('They, their');
    el.append(optel);
    optel = $('<option>', { value:'name' }).text(focuspane_special_val[1] + ', ' + focuspane_special_val[1] + "'s");
    el.append(optel);

    el = $('<div>', { 'class':'FocusDivider' });
    extrals.push(el);

    el = $('<p>', { 'class':'FormSelfDescLabel1 StyleEmph' });
    el.text('is...');
    extrals.push(el);

    el = $('<p>', { 'class':'FormSelfDescLabel2 StyleEmph' });
    el.text('pronoun...');
    extrals.push(el);

    return extrals;
}

function selfdesc_pronoun_changed() {
    var val = $('.FormSelfDescPronoun').prop('value');
    if (val == focuspane_special_val[2])
        return;

    focuspane_special_val[2] = val;
    selfdesc_update_labels();

    websocket_send_json({ cmd:'selfdesc', pronoun:val });
}

function selfdesc_desc_blur() {
    var val = $('.FormSelfDescDesc').prop('value');
    val = val.replace(new RegExp('\\s+', 'g'), ' ');
    val = jQuery.trim(val);
    if (!val)
        val = 'an ordinary explorer.';
    $('.FormSelfDescDesc').prop('value', val);

    if (val == focuspane_special_val[3])
        return;

    focuspane_special_val[3] = val;
    selfdesc_update_labels();

    websocket_send_json({ cmd:'selfdesc', desc:val });
}

function selfdesc_update_labels() {
    var val = focuspane_special_val[1] + ' is ' + focuspane_special_val[3];
    $('.FormSelfDescLabel1').text(val);

    switch (focuspane_special_val[2]) {
    case 'he':
        val = 'He is considering his appearance.';
        break;
    case 'she':
        val = 'She is considering her appearance.';
        break;
    case 'they':
        val = 'They are considering their appearance.';
        break;
    case 'name':
        val = focuspane_special_val[1] + ' is considering ' + focuspane_special_val[1] + '\'s appearance.';
        break;
    case 'it':
    default:
        val = 'It is considering its appearance.';
        break;
    }
    $('.FormSelfDescLabel2').text(val);
}

function editstr_build_controls() {
    /* ['editstr', key, value, extratext] */
    var extrals = [];
    var el, divel, optel;

    divel = $('<div>', { 'class':'FocusSection' });
    extrals.push(divel);
    el = $('<textarea>', { 'class':'FormEditStrValue FocusInput', rows:2,
                           autocapitalize:'on', autofocus:'autofocus',
                           name:'desc' });
    el.text(focuspane_special_val[2]);
    divel.append(el);

    return extrals;
}

function editstr_value_blur() {
    var val = $('.FormEditStrValue').prop('value');
    val = val.replace(new RegExp('\\s+', 'g'), ' ');
    val = jQuery.trim(val);
    $('.FormEditStrValue').prop('value', val);

    if (val == focuspane_special_val[2])
        return;

    focuspane_special_val[2] = val;
    websocket_send_json({ cmd:'action', action:focuspane_special_val[1], val:val });
}

/* All the commands that can be received from the server. */

function cmd_event(obj) {
    eventpane_add(obj.text);
}

function cmd_update(obj) {
    if (obj.world !== undefined) {
        toolpane_set_world(obj.world.world, obj.world.scope, obj.world.creator);
        /* Changing worlds is a good time to deselect the plist entry. */
        toolpane_plist_select(null);
    }
    if (obj.locale !== undefined) {
        localepane_set_locale(obj.locale.desc, obj.locale.name);
    }
    if (obj.populace !== undefined) {
        localepane_set_populace(obj.populace);
    }
    if (obj.focus !== undefined) {
        focuspane_special_val = [];
        focuspane_special_editplist = null;
        if (!obj.focus)
            focuspane_clear();
        else if (obj.focusspecial)
            focuspane_set_special(obj.focus);
        else
            focuspane_set(obj.focus);
        toolpane_portal_addremove();
    }
}

function cmd_updateplist(obj) {
    var seg = toolsegments['plist'];

    /* This could have a special case for adding one new portal to the end of
       the list. If we wanted keen animation, that is. */

    if (obj.clear) {
        seg.map = {};
    }

    if (obj.map) {
        jQuery.each(obj.map, function(portid, portal) {
                if (portal === false) {
                    delete seg.map[portid];
                }
                else {
                    seg.map[portid] = portal;
                }
            });
    }

    /* Rebuild the list, regardless. */
    seg.list.length = 0;
    jQuery.each(seg.map, function(portid, portal) {
            seg.list.push(portal);
        });
    seg.list.sort(function(p1, p2) { return p1.listpos - p2.listpos; });

    toolpane_plist_update();
}

var availscopemap = {};
var availscopelist = [];

function cmd_updatescopes(obj) {
    if (obj.clear) {
        availscopemap = {};
    }

    if (obj.map) {
        jQuery.each(obj.map, function(scid, scope) {
                if (scope === false) {
                    delete availscopemap[scid];
                }
                else {
                    availscopemap[scid] = scope;
                    /* Add a hacky sorting key */
                    if (scope.type == 'glob')
                        scope.sortkey = '0_';
                    else if (scope.type == 'pers' && scope.you)
                        scope.sortkey = '1_';
                    else if (scope.type == 'pers')
                        scope.sortkey = '2_' + scope.id;
                    else
                        scope.sortkey = '3_' + scope.id;
                }
            });
    }

    /* Rebuild the list, regardless. */
    availscopelist.length = 0;
    jQuery.each(availscopemap, function(scid, scope) {
            availscopelist.push(scope);
        });

    availscopelist.sort(function(p1, p2) {
            if (p1.sortkey < p2.sortkey)
                return -1;
            if (p1.sortkey > p2.sortkey)
                return 1;
            return 0;
        });

    /* Adjust the open tool pane, if necessary. */
    if (toolsegments['portal']) {
        toolpane_portal_update();
    }
}

function cmd_clearfocus(obj) {
    /* Same as update { focus:false }, really */
    focuspane_special_val = [];
    focuspane_special_editplist = null;
    focuspane_clear();
    toolpane_portal_addremove();
}

function cmd_message(obj) {
    eventpane_add(obj.text, 'EventMessage');
}

function cmd_error(obj) {
    eventpane_add('Error: ' + obj.text, 'EventError');
}

function cmd_extendcookie(obj) {
    /* Extend an existing cookie to a new date. */
    var key = obj.key;
    var date = obj.date;
    var re = new RegExp(key+'=([^;]*)');
    var match = re.exec(document.cookie);
    if (match) {
        var val = match[1];
        var newval = key+'='+val+';expires='+date;
        document.cookie = newval;
    }
}

var command_table = {
    event: cmd_event,
    update: cmd_update,
    updateplist: cmd_updateplist,
    updatescopes: cmd_updatescopes,
    clearfocus: cmd_clearfocus,
    message: cmd_message,
    error: cmd_error,
    extendcookie: cmd_extendcookie
};

/* Transform a description array (a JSONable array of strings and array tags)
   into a list of DOM elements. You can also pass in a raw string, which
   will be treated as a single unstyled paragraph.

   The description array is roughly parallel to HTML markup, with beginning
   and end tags for styles, and paragraph tags between (not around) paragraphs.
   We don't rely on jQuery's HTML-to-DOM features, though. We're going to
   build it ourselves, with verbose error reporting. (Authors will build
   this stuff interactively, and they deserve explicit bad-format warnings!)
*/
function parse_description(desc) {
    if (desc === null || desc === undefined)
        return [];

    if (!jQuery.isArray(desc))
        desc = [ desc ];

    var parals = [];
    var objstack = [];
    var elstack = [];

    /* It's easier if we keep a "current paragraph" around at all times.
       But we'll need to keep track of whether it's empty, because empty
       paragraphs shouldn't appear in the output. */
    var curpara = $('<p>');
    var curparasize = 0;
    var curinlink = false;
    parals.push(curpara);

    for (var ix=0; ix<desc.length; ix++) {
        var obj = desc[ix];
        var el = null;
        var parent;

        /* If we are going to add a new node, it will go on the most deeply-
           nested style, *or* the top-level paragraph (if there are no nested
           styles). Work this out now. */
        if (elstack.length == 0)
            parent = curpara;
        else
            parent = elstack[elstack.length-1];

        if (jQuery.isArray(obj)) {
            var objtag = obj[0];

            if (objtag == 'para') {
                if (objstack.length > 0) {
                    el = create_text_node('[Unclosed tags at end of paragraph]');
                    parent.append(el);
                    curparasize++;
                    objstack.length = 0;
                    elstack.length = 0;
                }

                if (curparasize == 0) {
                    /* We're already at the start of a fresh paragraph.
                       Just keep using it. */
                    continue;
                }

                curpara = $('<p>');
                curparasize = 0;
                curinlink = false;
                parals.push(curpara);
                continue;
            }

            if (objtag[0] == '/') {
                /* End an outstanding span. */
                if (objstack.length == 0) {
                    el = create_text_node('[End tag with no start tag]');
                    parent.append(el);
                    curparasize++;
                    continue;
                }

                var startobj = objstack[objstack.length-1];
                if (objtag == '/link') {
                    if (startobj[0] != 'link')
                        el = create_text_node('[Mismatched end of link]');
                    curinlink = false;
                }
                else if (objtag == '/exlink') {
                    if (startobj[0] != 'exlink')
                        el = create_text_node('[Mismatched end of external link]');
                    curinlink = false;
                }
                else if (objtag == '/style') {
                    if (startobj[0] != 'style')
                        el = create_text_node('[Mismatched end of style]');
                }
                else {
                    el = create_text_node('[Unrecognized end tag '+objtag+']');
                }

                if (el !== null) {
                    /* Paste on the error message. */
                    parent.append(el);
                    curparasize++;
                }

                objstack.length = objstack.length-1;
                elstack.length = elstack.length-1;
                continue;
            }
            else {
                /* Start a new span. */
                if (objtag == 'style') {
                    el = $('<span>');
                    var styleclass = description_style_classes[obj[1]];
                    if (!styleclass)
                        el.append(create_text_node('[Unrecognized style name]'));
                    else
                        el.addClass(styleclass);
                    objstack.push(obj);
                    elstack.push(el);
                }
                else if (objtag == 'link') {
                    if (curinlink)
                        parent.append(create_text_node('[Nested links]'));
                    var target = obj[1];
                    el = $('<a>', {href:'#'+target});
                    el.on('click', {target:target}, evhan_click_action);
                    objstack.push(obj);
                    elstack.push(el);
                    curinlink = true;
                }
                else if (objtag == 'exlink') {
                    /* External link -- distinct class, and opens in a new
                       window. */
                    if (curinlink)
                        parent.append(create_text_node('[Nested links]'));
                    el = $('<a>', { 'class': 'ExternalLink', 'target': '_blank', href:obj[1] });
                    objstack.push(obj);
                    elstack.push(el);
                    curinlink = true;
                }
                else {
                    el = create_text_node('[Unrecognized tag '+objtag+']');
                }

                parent.append(el);
                curparasize++;
            }
        }        
        else {
            /* String. */
            if (obj.length) {
                el = create_text_node(obj);
                parent.append(el);
                curparasize++;
            }
        }
    }

    if (objstack.length > 0) {
        var el = create_text_node('[Unclosed tags at end of text]');
        curpara.append(el);
        curparasize++;
    }

    if (curparasize == 0 && parals.length > 0) {
        /* The last paragraph never got any content. Remove it from
           the list. */
        parals.length = parals.length - 1;
    }

    return parals;
}

/* Create a plain text DOM node. Yeah, I do this sometimes. jQuery doesn't
   have a wrapper for this DOM operation. */
function create_text_node(val)
{
    return document.createTextNode(val);
}

/* Run a function (no arguments) in timeout seconds. Returns a value that
   can be passed to cancel_delayed_func(). */
function delay_func(timeout, func)
{
    return window.setTimeout(func, timeout*1000);
}

/* Cancel a delayed function. */
function cancel_delayed_func(val)
{
    window.clearTimeout(val);
}

/* Run a function (no arguments) "soon". */
function defer_func(func)
{
    return window.setTimeout(func, 0.01*1000);
}

function submit_line_input(val) {
    val = jQuery.trim(val);

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
        var start = val.charAt(0);
        if (start == ':') {
            websocket_send_json({ cmd:'pose', text:jQuery.trim(val.slice(1)) });
        }
        else if (start == '/') {
            /* Echo slash commands, because that's less confusing. */
            /* ### Should use a separate span for the >, so the style matches. */
            eventpane_add('> ' + val, 'EventEchoInput');
            websocket_send_json({ cmd:'meta', text:jQuery.trim(val.slice(1)) });
        }
        else {
            websocket_send_json({ cmd:'say', text:val });
        }
    }
}

var changed_uiprefs = {};
var uipref_changed_timer = null;

function note_uipref_changed(key)
{
    changed_uiprefs[key] = true;

    /* A bit of hysteresis; we don't send uiprefs until they've been
       stable for five seconds. */
    if (uipref_changed_timer)
        cancel_delayed_func(uipref_changed_timer);
    uipref_changed_timer = delay_func(2, send_uipref_changed);
}

function send_uipref_changed()
{
    if (!connected) {
        /* Leave changed_uiprefs full of keys. Maybe we can send it later. */
        return;
    }

    var obj = {};
    for (var key in changed_uiprefs) {
        obj[key] = uiprefs[key];
    }

    websocket_send_json({ cmd:'uiprefs', map:obj });
    changed_uiprefs = {};
}

/* Event handler: keypress events on input fields.

   Move the input focus to the event pane's input line.
*/
function evhan_doc_keypress(ev) {
    var keycode = 0;
    if (ev) keycode = ev.which;

    /* If we're not scrolled to the bottom, scroll to the bottom. Yes,
       we're going to check this on every single document keystroke.
       It doesn't seem to be necessary in Safari, but it does in Firefox. */
    var frameel = $('#eventpane');
    var bottomdiff = (frameel.get(0).scrollHeight - (frameel.scrollTop() + frameel.outerHeight()));
    if (bottomdiff > 0) {
        var newscrolltop = frameel.get(0).scrollHeight - frameel.outerHeight() + 2;
        if (!uiprefs.smooth_scroll)
            frameel.scrollTop(newscrolltop);
        else
            frameel.stop().animate({ 'scrollTop': newscrolltop }, 200);
    }
    
    var tagname = ev.target.tagName.toUpperCase();   
    if (tagname == 'INPUT' || tagname == 'TEXTAREA') {
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

function evhan_click_action(ev) {
    ev.preventDefault();

    var target = ev.data.target;
    websocket_send_json({ cmd:'action', action:target });
}

function evhan_click_dropfocus(ev) {
    ev.preventDefault();

    websocket_send_json({ cmd:'dropfocus' });
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

    uiprefs.leftright_percent = Math.round(percent);
    note_uipref_changed('leftright_percent');
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
    
    uiprefs.updown_percent = Math.round(percent);
    note_uipref_changed('updown_percent');
}


function evhan_websocket_open() {
    if (!everconnected) {
        /* Good time for a welcome message. */
        eventpane_add(localize('client.eventpane.start'), 'EventMessage');
    }

    connected = true;
    everconnected = true;
}

function evhan_websocket_close() {
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
    console.log(('### message: ' + ev.data).slice(0,100));
    var obj = null;
    var cmd = null;
    try {
        obj = JSON.parse(ev.data);
        cmd = obj.cmd;
    }
    catch (ex) {
        console.log('badly-formatted message from websocket: ' + ev.data);
        return;
    }

    var func = command_table[cmd];
    if (!func) {
        console.log('command not understood: ' + cmd);
        return;
    }

    func(obj);
}

function websocket_send_json(obj) {
    if (!connected) {
        /*### Maybe only show this error once. */
        eventpane_add('Error: You are not connected to the server.', 'EventError');
        console.log('websocket not connected');
        return;
    }

    var val = JSON.stringify(obj);
    websocket.send(val);
}

/* Return the localization of a string, as defined in the db_localize table.
   (Which was set up for us by tweb, using the localize data from the
   database.)
*/
function localize(key) {
    var res = db_localize[key];
    if (res)
        return res;
    /* Not found. Return a terrible default that people will notice. */
    return '** ' + key + ' **';
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    collate_uiprefs();
    build_page_structure();
    setup_event_handlers();
    open_websocket();
});
