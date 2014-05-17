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

Get the sources from <BuildPal GitHub repository `https://github.com/pkesist/buildpal`>_.

Building the Manager
--------------------

In the top-level project directory run the following::

    python setup_manager.py install


This will build the needed extensions and register the Manager with Python.
Once installed, the Manager can be run with::

    python -m buildpal_manager


Building the Server
-------------------

In the top-level project directory run the following::

    python setup_server.py install

Similar to Manager, this will build extensions and register the Server with Python.
It can be run with::

    python -m buildpal_server

Usually, you want to avoid installing Python on every machine on the build farm.
For this you can create an stand-alone distribution package with
:ref:`cx_Freeze <cx-freeze>`.


Building the Client
-------------------

::

    python setup_client.py build

The Client actually has nothing to with Python, so there is no point in
installing it. The compiler executable :file:`bp_cl.exe` will be produced in the
top-level project directory. To simplify its usage, consider moving the
executable somewhere on ``PATH``.

.. _cx-freeze::

Creating standalone packages with ``cx_Freeze``
-----------------------------------------------

.. _cx_Freeze: http://cx-freeze.sourceforge.net/

* Install cx_Freeze_.

.. note::

    Latest official cx_Freeze_ release (4.3.2) does not support Python 3.4 very
    well. Currently, creating a standalone package requires using a
    development version of cx_Freeze_ with several patches which have not yet
    been merged.

* In the ``Python`` subdirectory there are cx_Freeze_ scripts which to create
  standalone packages.

    * :file:`server_installer.py`
    * :file:`manager_installer.py`

* Typically you need to execute something like::

    python server_installer.py bdist_msi
    python manager_installer.py bdist_msi

  For more information try::

    python server_installer.py --help
    python manager_installer.py --help

