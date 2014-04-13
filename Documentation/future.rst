.. _future-wish-list:

Future development wish-list
============================

* Support more platforms.
    * GCC compiler support (Windows).
    * Clang compiler support (Windows).
    * Linux platform support (GCC/Clang).
    * ...

* IPV6 support.

* Support adding/removing farm nodes on-the-fly.

* Move task delegation logic from Manager to build farm.
    * This would make the farm 'client aware', providing better performance
      when multiple clients use the same farm.

* Object file caching support.
    * Farm could store object files, and return them later on in case of a
      duplicate request.

* Reporting.
    * Generate detailed report about build process.
    * Report information is already being collected and stored in the database,
      but is not yet user-friendly.