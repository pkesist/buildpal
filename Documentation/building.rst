Building BuildPal
=================

In order to build BuidlPal you need Python 3.4 with
`setuptools <http://pypi.python.org/pypi/setuptools>`_. Other dependencies will
be downloaded and built automatically. `setuptools`_ come bundled with
Python 3.4. If they are missing for some reason you can easily install them by
running::

    python -m ensurepip


Get the source from GitHub
--------------------------

.. todo::

    Write this once we upload to GitHub.


Building the Manager
--------------------

::

    python setup_manager.py install


This will build the needed extensions and register the Manager with Python.
Once installed, the Manager can be run with::

    python -m buildpal_manager


Building the Server
-------------------

::

    python setup_server.py install

Similar to Manager, this will build extensions and register the Server with Python.
It can be run with::

    python -m buildpal_server

Usually, you want to avoid installing Python on every machine on the build farm.
For this you can create an stand-alone distribution package with
`cx_Freeze <http://cx-freeze.sourceforge.net/>`_.

Building the Client
-------------------

::

    python setup_client.py build

The Client actually has nothing to with Python, so there is no point in
installing it. The Client executable will be produced in the current directory.
This executable should be put somewhere on PATH.

