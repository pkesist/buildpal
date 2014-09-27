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

        void markComplex( clang::FileEntry const & entry )
        {
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            container[ entry.getUniqueID() ].isComplex = true;
        }

        void storeHeaders( clang::FileEntry const & entry, Headers const & headers )
        {
            llvm::sys::fs::UniqueID id = entry.getUniqueID();
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            container[ id ].isComplex = false;
            container[ id ].headers = headers;
        }

        bool hasEntry( clang::FileEntry const & entry, bool & isComplex, Headers * & headers )
        {
            llvm::sys::fs::UniqueID id = entry.getUniqueID();
            boost::shared_lock<boost::shared_mutex> const lock( mutex );
            auto iter = container.find( id );
            if ( iter == container.end() )
                return false;
            isComplex = iter->second.isComplex;
            if ( !isComplex )
                headers = &iter->second.headers;
            return true;
        }

        boost::shared_mutex mutex;
        std::map<llvm::sys::fs::UniqueID, NaiveCacheEntry> container;
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
            fileEntry( other.fileEntry )
        {
            other.lexer = 0;
        }

        HeaderCtx & operator=( HeaderCtx && other )
        {
            currentHeader = std::move( other.currentHeader );
            lexer = other.lexer;
            other.lexer = 0;
            fileEntry = other.fileEntry;
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
        clang::HeaderSearch & headerSearch, clang::LangOptions & langOpts,
        Headers & result
    )
        : sourceManager_( sourceManager ), headerSearch_( headerSearch ),
        langOpts_( langOpts ), result_( result )
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
            mainFileBuffer,
            mainFileEntry,
            ContentEntryPtr(),
            true
        );
        clang::Token tok;
        while ( true )
        {
            bool done;
            bool found = findPreprocessorDirective( done );
            if ( !found )
            {
                if ( done )
                    return true;
                continue;
            }

            if ( !getToken( tok, done ) )
            {
                if ( done )
                    return true;
                continue;
            }

            if ( tok.isNot( clang::tok::raw_identifier ) )
                continue;

            llvm::StringRef directive( tok.getRawIdentifierData(), tok.getLength() );

            if ( directive == "include" )
            {
                if ( !handleInclude() )
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
        llvm::MemoryBuffer const * buffer,
        clang::FileEntry const * entry,
        ContentEntryPtr && content,
        bool relative
    )
    {
        Header header = { dir, name, content, relative };
        headerStack_.push_back
        (
            HeaderCtx
            (
                header,
                new clang::Lexer
                (
                    id,
                    buffer,
                    sourceManager_,
                    langOpts_
                ),
                entry
            )
        );
        alreadyVisited_.insert( entry );
    }

    bool handleEof()
    {
        NaivePreprocessorImpl::HeaderCtx const & headerCtx( headerStack_.back() );
        naiveCache.storeHeaders( *headerCtx.fileEntry, headerCtx.headers );
        Header header( headerStack_.back().currentHeader );
        Headers tmp( std::move( headerCtx.headers ) );
        headerStack_.pop_back();
        if ( headerStack_.empty() )
        {
            result_.swap( tmp );
            return true;
        }
        else
        {
            headerStack_.back().headers.insert( header );
            std::copy( tmp.begin(), tmp.end(), std::inserter( headerStack_.back().headers, headerStack_.back().headers.begin() ) );
            return false;
        }
    }

    bool handleInclude()
    {
        clang::Token tok;
        currentLexer().LexIncludeFilename( tok );
        llvm::SmallString<1024> searchPath;
        llvm::SmallString<1024> relativePath;
        if ( tok.isNot( clang::tok::angle_string_literal ) && tok.isNot( clang::tok::string_literal ) )
        {
            foundComplexInclude();
            return false;
        }
        bool const isAngled = tok.is( clang::tok::angle_string_literal );

        llvm::StringRef fileName( tok.getLiteralData() + 1, tok.getLength() - 2 );
        clang::DirectoryLookup const * curDir( 0 );
        clang::FileEntry const * fileEntry( headerSearch_.LookupFile( fileName, isAngled, 0, curDir, 
            headerStack_.back().fileEntry, &searchPath, &relativePath, NULL ) );
        if ( !fileEntry || ( alreadyVisited_.find( fileEntry ) != alreadyVisited_.end() ) )
            return true;

        {
            bool isComplex;
            Headers * cacheHeaders;
            if ( naiveCache.hasEntry( *fileEntry, isComplex, cacheHeaders ) )
            {
                if ( isComplex )
                {
                    foundComplexInclude();
                    return false;
                }
                else
                {
                    std::copy( cacheHeaders->begin(), cacheHeaders->end(),
                        std::inserter( headerStack_.back().headers,
                        headerStack_.back().headers.begin() )
                    );
                    return true;
                }
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

        ContentEntryPtr contentEntry = ContentCache::singleton().getOrCreate( sourceManager_.getFileManager(), fileEntry, NULL );
        clang::FileID const id = sourceManager_.createFileID
        (
            fileEntry,
            tok.getLocation(),
            headerSearch_.getFileDirFlavor( fileEntry )
        );

        pushHeader( 
            std::move( dir ),
            std::move( headerName ),
            id,
            contentEntry->buffer.get(),
            fileEntry,
            std::move( contentEntry ),
            relativeToParent
        );
        return true;
    }

    clang::Lexer & currentLexer() { return *headerStack_.back().lexer; }

    bool getToken( clang::Token & tok, bool & done )
    {
        bool result = currentLexer().LexFromRawLexer( tok );
        if ( result )
            done = handleEof();
        return !result;
    }

    bool findPreprocessorDirective( bool & done )
    {
        clang::Token tok;
        while ( true )
        {
            if ( !getToken( tok, done ) )
                return false;
            if ( tok.isNot( clang::tok::hash ) || !tok.isAtStartOfLine() )
                continue;
            return true;
        }
    }

private:
    void foundComplexInclude() const
    {
        std::for_each( headerStack_.begin() + 1, headerStack_.end(), []( HeaderCtx const & headerCtx )
        {
            naiveCache.markComplex( *headerCtx.fileEntry );
        });
    }

private:
    clang::SourceManager & sourceManager_;
    clang::HeaderSearch & headerSearch_;
    clang::LangOptions & langOpts_;
    Headers & result_;
    HeaderStack headerStack_;
    std::unordered_set<clang::FileEntry const *> alreadyVisited_;
};


NaivePreprocessor::NaivePreprocessor( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch, clang::LangOptions & langOpts,
        Headers & result
    ) :
    pImpl_( new NaivePreprocessorImpl( sourceManager, headerSearch, langOpts, result ) )
{
}

NaivePreprocessor::~NaivePreprocessor()
{
}

bool NaivePreprocessor::run()
{
    return pImpl_->run();
}

