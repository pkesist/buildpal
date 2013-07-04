//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <string>
#include <map>
#include <list>
#include <set>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class Preprocessor;
    class SourceManager;
    class FileEntry;
    class MacroDirective;
}


class HeaderTracker
{
public:
    typedef Preprocessor::HeaderRef Header;
    typedef Preprocessor::HeaderRefs Headers;
    typedef PreprocessingContext::IgnoredHeaders IgnoredHeaders;

    typedef std::string MacroDef;

    explicit HeaderTracker( clang::SourceManager & sm )
        : sourceManager_( sm ), preprocessor_( 0 ), shortCircuit_( 0 ),
        session_( 0 ) {}

    bool inclusionDirective( std::string const & relative, clang::FileEntry const * fileEntry, std::string * & );
    void headerSkipped( std::string const & relative, std::string const & filename );
    void enterHeader( std::string const & relative, std::string const & filename );
    Headers leaveHeader( IgnoredHeaders const & );

    void macroUsed( std::string const & name, clang::MacroDirective const * def );
    void macroDefined( std::string const & name, clang::MacroDirective const * def );
    void macroUndefined( std::string const & name, clang::MacroDirective const * def );

    void setPreprocessor( clang::Preprocessor * preprocessor )
    {
        preprocessor_ = preprocessor;
    }

    bool inOverriddenFile() const
    {
        return shortCircuit_ != 0;
    }

private:
    typedef std::pair<std::string, MacroDef> Macro;
    typedef std::set<Macro> MacroSet;
    typedef std::vector<Macro> MacroList;
    struct MacroUsage { enum Enum { macroUsed, macroDefined, macroUndefined }; };
    typedef std::list<std::pair<MacroUsage::Enum, Macro> > MacroUsages;

    struct ShortCircuitEntry
    {
        ShortCircuitEntry( unsigned sessionp, MacroUsages const & macroUsagesp, Headers const & headersp )
            : session( sessionp ), macroUsages( macroUsagesp ), headers( headersp )
        {}

        unsigned session;
        MacroUsages macroUsages;
        Headers headers;
    };
    
    struct HeaderShortCircuit : public std::map<MacroSet, ShortCircuitEntry> {};
    struct HeaderCacheSt : public std::map<Header, HeaderShortCircuit> {};
    struct MacroDefMap : public std::map<std::string, MacroDef> {};
    struct OverriddenHeaderContents : public std::map<std::pair<std::string, MacroSet>, std::string> {};

    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( Header const & header )
            : header_( header ) {}

        void addMacro( MacroUsage::Enum, Macro const & macro );
        void addHeader( Header const & header );

        void addStuff( MacroUsages const * macroUsages, Headers const * headers )
        {
            if ( macroUsages )
            {
                std::copy( macroUsages->begin(), macroUsages->end(),
                    std::back_inserter( macroUsages_ ) );
                normalize();
            }

            if ( headers )
            {
                std::copy( headers->begin(), headers->end(),
                    std::inserter( includedHeaders_, includedHeaders_.begin() ) );
            }
        }

        MacroUsages const & macroUsages() const { return macroUsages_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        Header const & header() { return header_; }
        MacroSet const usedMacros() const
        {
            std::set<std::string> defined;
            MacroSet result;
            for ( MacroUsages::const_iterator iter( macroUsages_.begin() ); iter != macroUsages_.end(); ++iter )
            {
                if ( iter->first == MacroUsage::macroDefined )
                    defined.insert( iter->second.first );
                if ( ( iter->first == MacroUsage::macroUsed ) && ( defined.find( iter->second.first ) == defined.end() ) )
                    result.insert( iter->second );
            }
            return result;
        }


        void normalize();

    private:
        Header header_;
        MacroUsages macroUsages_;
        Headers includedHeaders_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    HeaderCacheSt const & cache() const { return cache_; }
    HeaderCacheSt       & cache()       { return cache_; }

    clang::Preprocessor & preprocessor() const { assert( preprocessor_ ); return *preprocessor_; }
    clang::SourceManager & sourceManager() const { return sourceManager_; }

    MacroDef macroDefFromSourceLocation( clang::MacroDirective const * def );

private:
    clang::SourceManager & sourceManager_;
    clang::Preprocessor * preprocessor_;
    HeaderCtxStack headerCtxStack_;
    HeaderShortCircuit::value_type * shortCircuit_;
    HeaderCacheSt cache_;
    MacroDefMap currentFakeMacros_;
    OverriddenHeaderContents fakeMacroBuffers_;
    std::set<clang::FileEntry const *> mustNotOverride_;
    unsigned session_;
};


//------------------------------------------------------------------------------
#endif