.. _future-dev-plans:

Future development plans
========================

* Support more platforms.
    * GCC compiler support (Windows).
    * Clang compiler support (Windows).
    * Linux platform support (GCC/Clang).
    * ...

* Support adding/removing farm nodes during build.

* Move task delegation logic from Manager to build farm.
    * This would make the farm 'client aware', providing better performance
      when multiple clients use the same farm.

* Object file caching support.
    * Farm could store object files, and return them later on in case of a
      duplicate request.

* Reporting.
    * Generate detailed report about build process.
