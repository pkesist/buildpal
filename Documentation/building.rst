Building ``BuildPal``
=====================

.. _setuptools: http://pypi.python.org/pypi/setuptools

In order to build ``BuildPal`` you need:

    * ``Python 3.4`` (with setuptools_)
    * ``Visual C++ 2012 (11.0)``
    
Other dependencies will be downloaded and built automatically. setuptools_
comes bundled with Python 3.4. If it is missing for some reason you can easily
install it by running::

    python -m ensurepip


Get the sources from GitHub
---------------------------

Get the sources from `BuildPal GitHub repository <https://github.com/pkesist/buildpal>`_.

Building the Client
-------------------

In the top-level project directory run the following::

    python setup_client.py install

This will build the needed client-side extensions and install them in Python `site-packages`.

.. note::

    First time installation will take a while, as BuildPal will download
    and build its dependencies. Subsequent builds will be *much* faster. 

Once this is done, the Manager can be run with::

    python -m buildpal_manager

In addition, this will produce a client executable, :file:`bp_cl.exe` in the
top-level project directory. To simplify its usage, you might consider moving
the executable somewhere on ``PATH``.


Building the Server
-------------------

In the top-level project directory run the following::

    python setup_server.py install

Similar to Manager, this will build extensions and register the Server with Python.
It can be run with::

    python -m buildpal_server

.. _cx-freeze::

Creating standalone packages with ``cx_Freeze``
-----------------------------------------------

.. _cx_Freeze: http://cx-freeze.sourceforge.net/

Usually, you want to avoid installing Python on every machine on the build farm.
For this you can create an stand-alone distribution package with
cx_Freeze_.


* Install cx_Freeze_.

.. note::

    You need to use cx_Freeze_ 4.3.3 or newer. Previous releases do not support
    Python 3.4 very well.

* In the ``Python`` subdirectory there are cx_Freeze_ scripts for creating
  standalone packages.

    * :file:`standalone_manager.py`
    * :file:`standalone_server.py`

* Typically you need to execute something like::

    python standalone_server.py bdist_msi
    python standalone_server.py bdist_msi

  For more information try::

    python standalone_server.py --help
    python standalone_server.py --help

