//------------------------------------------------------------------------------
#ifndef naivePreprocessor_HPP__B9D294E8_FCA3_45AE_8404_8BE1D20F8A08
#define naivePreprocessor_HPP__B9D294E8_FCA3_45AE_8404_8BE1D20F8A08
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <memory>
//------------------------------------------------------------------------------

namespace clang
{
    class SourceManager;
    class HeaderSearch;
    class LangOptions;
};


class NaivePreprocessorImpl;
class NaivePreprocessor
{
public:
    NaivePreprocessor( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch, clang::LangOptions & langOpts,
        Headers & result
    );
    ~NaivePreprocessor();

    bool run();

private:
    std::unique_ptr<NaivePreprocessorImpl> pImpl_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
