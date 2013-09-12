function evhan_change_pw(ev) {
    ev.preventDefault();

    $('#change_pw_form').slideDown(400);
}

/* The page-ready handler. Like onload(), but better, I'm told. */
$(document).ready(function() {
    $('#change_pw_link').on('click', evhan_change_pw);
});

