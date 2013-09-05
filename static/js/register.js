
/* This is a purely cosmetic bit of script. It updates the "... waves to
   the camera" line of the web form, as the player types. 
*/

function evhan_input(ev) {
    var val = $('#login_field').prop('value');
    val = jQuery.trim(val);

    if (val) {
        $('#name_display_label').text(val);
    }
    else {
        var el = $('<em>').text('Player Name');
        $('#name_display_label').empty();
        $('#name_display_label').append(el);
    }
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    $('#login_field').on('input', evhan_input);
    /* Call the hook manually, to fill in the initial value. */
    evhan_input(null);
});
