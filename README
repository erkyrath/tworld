Tworld -- a choice-based shared online text environment sandbox

Tworld pre-release version 0.10.
Designed by Andrew Plotkin <erkyrath@eblong.com>.
Site: <https://github.com/erkyrath/tworld>

Tworld is a text MUD engine in a new style. It runs as a web application,
offering hypertext environments (hyperlink-based actions rather than a
command line). Players can construct new areas in a wiki-style interface.
The intent is to have a modern, easily-accessible shared world, which
blends the lightweight social environment of a chat MUD with the inviting
collaborative sandbox of a wiki.


* Caveats

Tworld is still in development. It is not finished yet! I'd be willing
to call it "beta", but with a lot of lip-pursing and squinting.

The scripting language is mostly defined, but is missing large chunks
of functionality.

The database schema is also mostly defined. Future changes will come
with a database-upgrade script (twsetup.py --upgradedb).


* Requirements

Python 3 (3.3 or later)
MongoDB (2.4 or later) (not tested with 2.5 or 2.6)
Tornado (3.1 or later) (not tested with 3.2)
PyMongo (2.4 or later)
Motor (0.1)

Typically you will install Python 3 and MongoDB with your package manager;
on MacOS, I use Homebrew. Python comes with its own package manager, pip3;
use this to install Tornado, PyMongo, and Motor.

Note: the latest version of Motor (0.1.2) specifies the not-quite-latest
version of PyMongo (2.5.0). This is a nuisance. I am currently using
PyMongo 2.5.2 with Motor 0.1, which seems to work with a simple Mongo
configuration. Do not try this with replica sets.


* Installation notes

At the moment, you're on your own. I will regularize and document this
as the system gets closer to beta.

The overview: Tworld runs as a trio of daemon processes (mongod, tweb, and
tworld). To run them, you will need a private server, or a shared compute
service such as Linode or Amazon EC2. Tworld is not suitable for a shared
web-hosting service; these usually forbid long-running processes such as
chat and MUD apps.

Once you have installed everything, edit tworld.conf to your liking.
(The admin_email entry should be a real email address.)

Make sure mongodb is running.

Run the setup script:
python3 twsetup.py --config=tworld.conf

Then start the tworld and tweb processes, in separate shells:
python3 tworld.py --config=tworld.conf
python3 tweb.py --config=tworld.conf


* License

Copyright (c) 2013-2014, Andrew Plotkin.
Open-source under the MIT license. See the "LICENSE" file.

This package includes the following third-party software:

  jQuery JavaScript Library v1.9.1
    http://jquery.com/  (MIT license)
  jQuery UI v1.10.3
    http://jqueryui.com  (MIT license)
  jQuery.contextMenu version 1.7 (with modifications)
    https://github.com/arnklint/jquery-contextMenu  (public domain)
  jQuery Autosize v1.17.1
    https://github.com/jackmoore/autosize  (MIT license)
