Rants
=====

Why local preprocessing does not work well with MSVC
----------------------------------------------------

MS Visual C++ compiler does not really have a preprocessing step when
compiling. It tries to optimize the compilation processes and memory usage
by going through the file only once, performing both preprocesing and
tokenization at once, line by line. Manually running the preprocessor, and
then compiling the preprocessed result significantly increases the compilation
time. Consequently, trying to distribute compilation of locally preprocessed
source files incurs an apriori time penalty. This approach can generate
work for only 2-3 additional slaves at best. To make matters worse, MSVC++
is generally `unable \
<http://connect.microsoft.com/VisualStudio/feedback/details/783043/>`_
to compile preprocessed output it generates.
