function evhan_change_pw(ev) {
    ev.preventDefault();

    $('#change_pw_form').slideDown(400);
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    /* Hide the pw-change form. (We do this in JS so that it's available
       by default when JS is turned off.) */
    if (!show_pwchange_initially) {
        $('#change_pw_form').hide();
    }

    $('#change_pw_link').on('click', evhan_change_pw);
});

