#include "naivePreprocessor_.hpp"

#include "contentCache_.hpp"

#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/HeaderSearch.h>

#include <unordered_set>

namespace
{
    struct NaiveCache
    {
        struct NaiveCacheEntry
        {
            Headers headers;
            bool isComplex;
        };

        void markComplex( clang::FileEntry const & entry, std::size_t searchPathId )
        {
            CacheKey const key = std::make_pair( entry.getUniqueID(), searchPathId );
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            container[ key ].isComplex = true;
        }

        void storeHeaders( clang::FileEntry const & entry, std::size_t searchPathId, Headers && headers )
        {
            CacheKey const key = std::make_pair( entry.getUniqueID(), searchPathId );
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            auto iter = container.find( key );
            if ( iter != container.end() )
            {
                assert( ( iter == container.end() ) || !iter->second.isComplex );
                assert( ( iter == container.end() ) || ( iter->second.headers == headers ) );
            }
            else
            {
                container[ key ].isComplex = false;
                container[ key ].headers = headers;
            }
        }

        bool hasEntry( clang::FileEntry const & entry, std::size_t searchPathId, bool & isComplex, Headers & headers )
        {
            boost::shared_lock<boost::shared_mutex> const lock( mutex );
            auto iter = container.find( std::make_pair( entry.getUniqueID(), searchPathId ) );
            if ( iter == container.end() )
                return false;
            isComplex = iter->second.isComplex;
            if ( !isComplex )
                headers = iter->second.headers;
            return true;
        }

    private:
        boost::shared_mutex mutex;
        typedef std::pair<llvm::sys::fs::UniqueID, std::size_t> CacheKey;
        std::map<CacheKey, NaiveCacheEntry> container;
    } naiveCache;
}  // anonymous namespace

class NaivePreprocessorImpl
{
private:
    struct HeaderCtx
    {
    private:
        HeaderCtx( HeaderCtx const & );
        HeaderCtx & operator=( HeaderCtx const & );

    public:
        HeaderCtx( Header const & h, clang::Lexer * l, clang::FileEntry const * f )
            : currentHeader( h ), lexer( l ), fileEntry( f )
        {
        }

        HeaderCtx( HeaderCtx && other )
            : currentHeader( std::move( other.currentHeader ) ),
            lexer( other.lexer ),
            fileEntry( other.fileEntry ),
            headers( std::move( other.headers ) )
        {
            other.lexer = 0;
        }

        HeaderCtx & operator=( HeaderCtx && other )
        {
            currentHeader = std::move( other.currentHeader );
            lexer = other.lexer;
            other.lexer = 0;
            fileEntry = other.fileEntry;
            headers.swap( other.headers );
            return *this;
        }

        ~HeaderCtx()
        {
            delete lexer;
        }

        Header currentHeader;
        clang::Lexer * lexer;
        clang::FileEntry const * fileEntry;
        Headers headers;
    };

    typedef std::vector<HeaderCtx> HeaderStack;

public:
    NaivePreprocessorImpl( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch, std::size_t searchPathId,
        clang::LangOptions & langOpts, PreprocessingContext::Includes const &
        forcedIncludes, Headers & result )
        : sourceManager_( sourceManager ), headerSearch_( headerSearch ),
        searchPathId_( searchPathId ), langOpts_( langOpts ),
        forcedIncludes_( forcedIncludes ), result_( result )
    {}

    bool run()
    {
        clang::FileID const mainFileID = sourceManager_.getMainFileID();
        clang::FileEntry const * mainFileEntry = sourceManager_.getFileEntryForID( mainFileID );
        llvm::MemoryBuffer const * mainFileBuffer = sourceManager_.getMemoryBufferForFile( mainFileEntry );
        pushHeader(
            Dir( mainFileEntry->getDir()->getName() ),
            HeaderName( mainFileEntry->getName() ),
            mainFileID,
            mainFileEntry,
            true
        );

        for ( PreprocessingContext::Includes::value_type const & include : forcedIncludes_ )
        {
            if ( !handleInclude( include, false, clang::SourceLocation() ) )
                return false;
        }

        clang::Token tok;
        while ( true )
        {
            clang::Token tok;
            if ( !findPreprocessorDirective( tok ) )
                return true;

            llvm::StringRef const directive( tok.getRawIdentifier() );
            if ( directive == "include" )
            {
                clang::Token tok;
                currentLexer().LexIncludeFilename( tok );
                if ( tok.isNot( clang::tok::angle_string_literal ) && tok.isNot( clang::tok::string_literal ) )
                {
                    foundComplexInclude();
                    return false;
                }
                bool const isAngled = tok.is( clang::tok::angle_string_literal );
                llvm::StringRef fileName( tok.getLiteralData() + 1, tok.getLength() - 2 );

                if ( !handleInclude( fileName, isAngled, tok.getLocation() ) )
                    return false;
            }
        }
    }

private:
    void pushHeader
    (
        Dir && dir,
        HeaderName && name,
        clang::FileID id,
        clang::FileEntry const * entry,
        bool relative
    )
    {
        ContentEntryPtr contentEntry = ContentCache::singleton().getOrCreate( sourceManager_.getFileManager(), entry, NULL );
        Header header = { dir, name, contentEntry, relative };

        headerStack_.push_back
        (
            HeaderCtx
            (
                header,
                new clang::Lexer
                (
                    id,
                    contentEntry->buffer.get(),
                    sourceManager_,
                    langOpts_
                ),
                entry
            )
        );
    }

    bool handleEof()
    {
        NaivePreprocessorImpl::HeaderCtx headerCtx( std::move( headerStack_.back() ) );
        headerStack_.pop_back();
        if ( headerStack_.empty() )
        {
            result_.swap( headerCtx.headers );
            return true;
        }
        else
        {
            headerCtx.headers.insert( headerCtx.currentHeader );
            std::copy( headerCtx.headers.begin(), headerCtx.headers.end(),
                std::inserter(
                    headerStack_.back().headers,
                    headerStack_.back().headers.begin()
                )
            );
            naiveCache.storeHeaders( *headerCtx.fileEntry, searchPathId_, std::move( headerCtx.headers ) );
            return false;
        }
    }

    bool handleInclude( llvm::StringRef fileName, bool isAngled, clang::SourceLocation loc )
    {
        llvm::SmallString<1024> searchPath;
        llvm::SmallString<1024> relativePath;
        clang::DirectoryLookup const * curDir( 0 );
        clang::FileEntry const * fileEntry( headerSearch_.LookupFile( fileName, loc, isAngled, 0, curDir,
            headerStack_.back().fileEntry, &searchPath, &relativePath, NULL ) );
        if ( !fileEntry )
            return true;

        if ( std::find_if( headerStack_.begin(), headerStack_.end(),
            [=]( HeaderCtx const & headerCtx )
            {
                return headerCtx.fileEntry == fileEntry;
            }) != headerStack_.end() )
            return true;

        {
            bool isComplex;
            Headers cacheHeaders;
            if ( naiveCache.hasEntry( *fileEntry, searchPathId_, isComplex, cacheHeaders ) )
            {
                if ( isComplex )
                {
                    foundComplexInclude();
                    return false;
                }
                std::copy( cacheHeaders.begin(), cacheHeaders.end(),
                    std::inserter( headerStack_.back().headers,
                    headerStack_.back().headers.begin() )
                );
                return true;
            }
        }

        Dir dir;
        HeaderName headerName;

        bool const relativeToParent( !isAngled && ( headerStack_.back().fileEntry->getDir()->getName() == searchPath ) );
        if ( relativeToParent )
        {
            dir =  Dir( headerStack_.back().currentHeader.dir );
            llvm::StringRef const parentFilename = headerStack_.back().currentHeader.name.get();
            std::size_t const slashPos = parentFilename.find_last_of('/');
            if ( slashPos == llvm::StringRef::npos )
                headerName = HeaderName( relativePath );
            else
            {
                llvm::SmallString<512> fileName( parentFilename.data(), parentFilename.data() + slashPos + 1 );
                fileName.append( relativePath );
                headerName = HeaderName( fileName.str() );
            }
        }
        else
        {
            dir = Dir( searchPath );
            headerName = HeaderName( relativePath );
        }

        clang::FileID const id = sourceManager_.createFileID
        (
            fileEntry,
            loc,
            headerSearch_.getFileDirFlavor( fileEntry )
        );

        pushHeader(
            std::move( dir ),
            std::move( headerName ),
            id,
            fileEntry,
            relativeToParent
        );
        return true;
    }

    clang::Lexer & currentLexer() { return *headerStack_.back().lexer; }

    bool getToken( clang::Token & tok, bool & done )
    {
        bool result = currentLexer().LexFromRawLexer( tok );
        done = result ? handleEof() : false;
        return !result;
    }

    bool findPreprocessorDirective( clang::Token & tok )
    {
        bool done = false;
        while ( true )
        {
            if ( !getToken( tok, done ) )
            {
                if ( done )
                    return false;
                continue;
            }
            if ( tok.isNot( clang::tok::hash ) || !tok.isAtStartOfLine() )
                continue;
            while ( tok.is( clang::tok::hash ) && tok.isAtStartOfLine() )
                if ( !getToken( tok, done ) )
                {
                    if ( done )
                        return false;
                    continue;
                }
            if ( tok.isNot( clang::tok::raw_identifier ) )
                continue;
            return true;
        }
    }

private:
    void foundComplexInclude() const
    {
        std::for_each( headerStack_.begin() + 1, headerStack_.end(), [this]( HeaderCtx const & headerCtx )
        {
            naiveCache.markComplex( *headerCtx.fileEntry, searchPathId_ );
        });
    }

private:
    clang::SourceManager & sourceManager_;
    clang::HeaderSearch & headerSearch_;
    std::size_t searchPathId_;
    clang::LangOptions & langOpts_;
    PreprocessingContext::Includes const & forcedIncludes_;
    Headers & result_;
    HeaderStack headerStack_;
};


NaivePreprocessor::NaivePreprocessor( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch, std::size_t searchPathId,
        clang::LangOptions & langOpts, PreprocessingContext::Includes const &
        forcedIncludes, Headers & result
    ) :
    pImpl_( new NaivePreprocessorImpl( sourceManager, headerSearch,
        searchPathId, langOpts, forcedIncludes, result ) )
{
}

NaivePreprocessor::~NaivePreprocessor()
{
}

bool NaivePreprocessor::run()
{
    return pImpl_->run();
}

