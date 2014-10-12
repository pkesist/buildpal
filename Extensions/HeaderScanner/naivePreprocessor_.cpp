#include "naivePreprocessor_.hpp"

#include "contentCache_.hpp"

#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/HeaderSearch.h>

#include <unordered_set>

struct IncludeDirective
{
    std::string filename;
    clang::SourceLocation loc;
    bool isAngled;
};

typedef std::vector<IncludeDirective> IncludeDirectives;

namespace
{
    struct NaiveCacheEntry
    {
        bool complex;    
        IncludeDirectives includes;    
    };

    struct NaiveCache
    {

        NaiveCache( ContentCache & contentCache )
            : conn_
            (
                contentCache.registerFileChangedCallback
                (
                    std::bind( &NaiveCache::invalidate, this, std::placeholders::_1 )
                )
            )
        {
        }

        void markComplex( clang::FileEntry const * entry )
        {
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            container[ entry->getUniqueID() ].complex = true;
        }
        
        void store( clang::FileEntry const * entry, IncludeDirectives && includes )
        {
            boost::unique_lock<boost::shared_mutex> const lock( mutex );
            container[ entry->getUniqueID() ].complex = false;
            container[ entry->getUniqueID() ].includes = std::move( includes );
        }

        bool lookup( clang::FileEntry const * entry, bool & complex, IncludeDirectives & includes )
        {
            boost::shared_lock<boost::shared_mutex> const lock( mutex );
            auto iter = container.find( entry->getUniqueID() );
            if ( iter == container.end() )
                return false;
            complex = iter->second.complex;
            if ( !complex )
                includes = iter->second.includes;
            return true;
        }

    private:
        struct HashUniqueId
        {
            std::size_t operator()( llvm::sys::fs::UniqueID const & val ) const
            {
                return llvm::hash_combine(
                    llvm::hash_value( val.getDevice() ),
                    llvm::hash_value( val.getFile() )
                );
            }
        };

        void invalidate( ContentEntry const & entry )
        {
            boost::shared_lock<boost::shared_mutex> const lock( mutex );
            container.erase( entry.status.getUniqueID() );
        }

    private:
        boost::signals2::scoped_connection conn_;
        boost::shared_mutex mutex;
        std::unordered_map<llvm::sys::fs::UniqueID, NaiveCacheEntry, HashUniqueId> container;
    } naiveCache( ContentCache::singleton() );
}  // anonymous namespace

struct IncludeFinder
{
    struct NextIncludeResult
    {
        enum Enum
        {
            nirIncludeFound,
            nirHeaderDone,
            nirHeaderComplex
        };
    };

    virtual NextIncludeResult::Enum nextInclude( IncludeDirective & ) = 0;
};

struct FixedIncludeFinder : IncludeFinder
{
    explicit FixedIncludeFinder( IncludeDirectives && includes )
        : includes_( std::move( includes ) ),
        iter_( includes_.begin() )
    {
    }
        
    NextIncludeResult::Enum nextInclude( IncludeDirective & d ) override
    {
        if ( iter_ == includes_.end() )
            return NextIncludeResult::nirHeaderDone;
        d = *(iter_++);
        return NextIncludeResult::nirIncludeFound;
    }

    IncludeDirectives includes_;
    IncludeDirectives::iterator iter_;
};

struct LexingIncludeFinder : IncludeFinder
{
    LexingIncludeFinder( std::unique_ptr<clang::Lexer> && lex, clang::FileEntry const * entry )
        : lexer_( std::move( lex ) ), entry_( entry )
    {
    }

    NextIncludeResult::Enum nextInclude( IncludeDirective & d ) override
    {
        clang::Token tok;
        for ( ; ; )
        {
            if ( lexer().LexFromRawLexer( tok ) )
            {
                naiveCache.store( entry_, std::move( includes_ ) );
                return NextIncludeResult::nirHeaderDone;
            }
            if ( tok.isNot( clang::tok::hash ) || !tok.isAtStartOfLine() )
                continue;
            while ( tok.isNot( clang::tok::raw_identifier ) && ( tok.is( clang::tok::hash ) && tok.isAtStartOfLine() ) )
            {
                if ( lexer().LexFromRawLexer( tok ) )
                {
                    naiveCache.store( entry_, std::move( includes_ ) );
                    return NextIncludeResult::nirHeaderDone;
                }
            }
            if ( tok.getRawIdentifier() != "include" )
                continue;

            lexer().setParsingPreprocessorDirective( true );
            lexer().LexIncludeFilename( tok );
            lexer().setParsingPreprocessorDirective( false );

            if ( tok.isNot( clang::tok::angle_string_literal ) && tok.isNot( clang::tok::string_literal ) )
                return NextIncludeResult::nirHeaderComplex;

            d.filename = llvm::StringRef( tok.getLiteralData() + 1, tok.getLength() - 2 );
            d.loc = tok.getLocation();
            d.isAngled = tok.is( clang::tok::angle_string_literal );
            includes_.push_back( d );
            return NextIncludeResult::nirIncludeFound;
        }
    }

    clang::Lexer & lexer() { return *lexer_; }

    std::unique_ptr<clang::Lexer> lexer_;
    clang::FileEntry const * entry_;
    IncludeDirectives includes_;
};

class NaivePreprocessorImpl
{
private:
    struct HeaderCtx
    {
    private:
        HeaderCtx( HeaderCtx const & );
        HeaderCtx & operator=( HeaderCtx const & );

    public:
        HeaderCtx( Header const & h, std::unique_ptr<IncludeFinder> i, clang::FileEntry const * f )
            : currentHeader( h ), includeFinder( std::move( i ) ), fileEntry( f )
        {
        }

        HeaderCtx( HeaderCtx && other )
            : currentHeader( std::move( other.currentHeader ) ),
            includeFinder( std::move( other.includeFinder ) ),
            fileEntry( other.fileEntry ),
            includes( std::move( other.includes ) )
        {
        }

        HeaderCtx & operator=( HeaderCtx && other )
        {
            currentHeader = std::move( other.currentHeader );
            includeFinder = std::move( other.includeFinder );
            fileEntry = other.fileEntry;
            includes.swap( other.includes );
            return *this;
        }

        Header currentHeader;
        std::unique_ptr<IncludeFinder> includeFinder;
        clang::FileEntry const * fileEntry;
        IncludeDirectives includes;
    };

    typedef std::vector<HeaderCtx> HeaderStack;

public:
    NaivePreprocessorImpl( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch, clang::LangOptions & langOpts,
        PreprocessingContext::Includes const & forcedIncludes,
        Headers & result )
        : sourceManager_( sourceManager ), headerSearch_( headerSearch ),
        langOpts_( langOpts ), forcedIncludes_( forcedIncludes ),
        result_( result )
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
            IncludeDirective includeDirective = { include, clang::SourceLocation(), false };
            if ( !handleInclude( includeDirective ) )
                return false;
        }

        while ( !headerStack_.empty() )
        {
            IncludeDirective includeDirective;
            switch ( headerStack_.back().includeFinder->nextInclude( includeDirective ) )
            {
            case IncludeFinder::NextIncludeResult::nirIncludeFound:
                if ( !handleInclude( includeDirective ) )
                    return false;
                break;
            case IncludeFinder::NextIncludeResult::nirHeaderDone:
                popHeader();
                break;
            case IncludeFinder::NextIncludeResult::nirHeaderComplex:
                for ( NaivePreprocessorImpl::HeaderCtx const & headerCtx : headerStack_ )
                    naiveCache.markComplex( headerCtx.fileEntry );
                return false;
            }
        }
        result_.swap( allHeaders_ );
        return true;

    }

private:
    void pushHeader
    (
        Dir && dir,
        HeaderName && name,
        clang::FileID id,
        clang::FileEntry const * entry,
        bool relative,
        IncludeDirectives * includeDirectives = 0
    )
    {
        ContentEntryPtr contentEntry = ContentCache::singleton().getOrCreate( entry->getName() ).get();

        IncludeFinder * includeFinder;
        if ( includeDirectives )
        {
            includeFinder = new FixedIncludeFinder( std::move( *includeDirectives ) );
        }
        else
        {
            includeFinder = new LexingIncludeFinder
            (
                std::unique_ptr<clang::Lexer>
                (
                    new clang::Lexer
                    (
                        id,
                        contentEntry->buffer.get(),
                        sourceManager_,
                        langOpts_
                    )
                ),
                entry
            );
        }
    
        Header header = { dir, name, contentEntry, relative };
        headerStack_.push_back
        (
            HeaderCtx
            (
                header,
                std::unique_ptr<IncludeFinder>( includeFinder ),
                entry
            )
        );
    }

    void popHeader()
    {
        NaivePreprocessorImpl::HeaderCtx headerCtx( std::move( headerStack_.back() ) );
        headerStack_.pop_back();
        if ( !headerStack_.empty() )
            allHeaders_.insert( headerCtx.currentHeader );
    }

    bool handleInclude( IncludeDirective const & includeDirective )
    {
        llvm::SmallString<1024> searchPath;
        llvm::SmallString<1024> relativePath;
        clang::DirectoryLookup const * curDir( 0 );
        // Will be used with Clang 3.6.
        //llvm::SmallVector<std::pair<clang::FileEntry const *, clang::DirectoryEntry const *>, 16> includers;
        //includers.push_back( std::make_pair( headerStack_.back().fileEntry, headerStack_.back().fileEntry->getDir() ) );
        clang::FileEntry const * fileEntry(
            headerSearch_.LookupFile(
                includeDirective.filename,
                includeDirective.loc,
                includeDirective.isAngled,
                0,
                curDir,
                headerStack_.back().fileEntry,
                &searchPath,
                &relativePath,
                NULL
            )
        );

        if ( !fileEntry || !alreadyVisited_.insert( fileEntry ).second )
            return true;

        bool foundInCache;
        bool complex;
        IncludeDirectives cachedIncludeDirectives;
        if ( foundInCache = naiveCache.lookup( fileEntry, complex, cachedIncludeDirectives ) )
        {
            if ( complex )
                return false;
        }

        Dir dir;
        HeaderName headerName;

        bool const relativeToParent( !includeDirective.isAngled && ( headerStack_.back().fileEntry->getDir()->getName() == searchPath ) );
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
            includeDirective.loc,
            headerSearch_.getFileDirFlavor( fileEntry )
        );

        pushHeader(
            std::move( dir ),
            std::move( headerName ),
            id,
            fileEntry,
            relativeToParent,
            foundInCache ? &cachedIncludeDirectives : 0
        );
        return true;
    }

private:
    typedef std::unordered_set<clang::FileEntry const *> AlreadyVisited;

private:
    clang::SourceManager & sourceManager_;
    clang::HeaderSearch & headerSearch_;
    clang::LangOptions & langOpts_;
    PreprocessingContext::Includes const & forcedIncludes_;
    Headers allHeaders_;
    AlreadyVisited alreadyVisited_;
    Headers & result_;
    HeaderStack headerStack_;
};


NaivePreprocessor::NaivePreprocessor( clang::SourceManager & sourceManager,
        clang::HeaderSearch & headerSearch,
        clang::LangOptions & langOpts, PreprocessingContext::Includes const &
        forcedIncludes, Headers & result
    ) :
    pImpl_( new NaivePreprocessorImpl( sourceManager, headerSearch,
        langOpts, forcedIncludes, result ) )
{
}

NaivePreprocessor::~NaivePreprocessor()
{
}

bool NaivePreprocessor::run()
{
    return pImpl_->run();
}

