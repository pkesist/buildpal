//------------------------------------------------------------------------------
#include "contentCache_.hpp"
#include "headerScanner_.hpp"
#include "headerTracker_.hpp"
#include "utility_.hpp"

#include <clang/Basic/Diagnostic.h>
#include <clang/Basic/DiagnosticOptions.h>
#include <clang/Basic/FileSystemStatCache.h>
#include <clang/Basic/MacroBuilder.h>
#include <clang/Basic/TargetInfo.h>
#include <clang/Basic/TokenKinds.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/HeaderSearch.h>
#include <clang/Lex/HeaderSearchOptions.h>
#include <clang/Lex/LexDiagnostic.h>
#include <clang/Lex/ModuleLoader.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/PreprocessorOptions.h>
#include <clang/Rewrite/Frontend/Rewriters.h>
#include <llvm/Config/config.h>
#include <llvm/Support/Host.h>
#include <llvm/Support/Path.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/ADT/SmallString.h>

#include <iostream>
#include <windows.h>

namespace
{
    struct DummyModuleLoader : public clang::ModuleLoader 
    {
        virtual clang::ModuleLoadResult loadModule(
            clang::SourceLocation,
            clang::ModuleIdPath,
            clang::Module::NameVisibilityKind,
            bool IsInclusionDirective) { return clang::ModuleLoadResult(); }
        virtual void makeModuleVisible(
            clang::Module *,
            clang::Module::NameVisibilityKind,
            clang::SourceLocation,
            bool Complain) {}
    } moduleLoader;
}

void normalize( llvm::SmallString<512> & path )
{
    llvm::SmallString<512> result;

    llvm::sys::path::const_iterator const end = llvm::sys::path::end( path.str() );
    for ( llvm::sys::path::const_iterator iter = llvm::sys::path::begin( path.str() ); iter != end; ++iter )
    {
        if ( *iter == "." )
            continue;
        else if ( *iter == ".." )
        {
            assert( !result.empty() );
            llvm::sys::path::remove_filename( result );
        }
        else
        {
            llvm::sys::path::append( result, *iter );
        }
    }
    llvm::sys::path::native( result );
    path.swap( result );
}

namespace
{
    class PreprocessorCallbacks : public clang::PPCallbacks
    {
    public:
        explicit PreprocessorCallbacks
        (
            HeaderTracker & headerTracker,
            llvm::StringRef filename,
            clang::Preprocessor & preprocessor,
            Headers & includedHeaders,
            HeaderList & missingHeaders
        )
            :
            headerTracker_ ( headerTracker   ),
            preprocessor_  ( preprocessor    ),
            headers_       ( includedHeaders ),
            missingHeaders_( missingHeaders  ),
            filename_      ( filename        )
        {
        }

        virtual ~PreprocessorCallbacks() {}

        virtual void InclusionDirective(
            clang::SourceLocation hashLoc,
            clang::Token const & includeTok,
            llvm::StringRef fileName,
            bool isAngled,
            clang::CharSourceRange filenameRange,
            clang::FileEntry const * file,
            llvm::StringRef searchPath,
            llvm::StringRef relativePath,
            clang::Module const * imported) LLVM_OVERRIDE
        {
            if ( !file )
            {
                missingHeaders_.insert( fileName.str() );
                return;
            }

            headerTracker_.inclusionDirective( searchPath, relativePath, fileName, isAngled, file );
        }

#ifdef ReplaceFile
#undef ReplaceFile
#endif
        virtual void ReplaceFile( clang::FileEntry const * & file ) LLVM_OVERRIDE
        {
            headerTracker_.replaceFile( file );
        }

        virtual void FileChanged( clang::SourceLocation loc, FileChangeReason reason,
            clang::SrcMgr::CharacteristicKind, clang::FileID exitedFID ) LLVM_OVERRIDE
        {
            if ( reason == EnterFile )
            {
                clang::FileID const fileId( preprocessor_.getSourceManager().getFileID( loc ) );
                clang::FileEntry const * const fileEntry( preprocessor_.getSourceManager().getFileEntryForID( fileId ) );
                if ( !fileEntry )
                    return;
                if ( fileId == preprocessor_.getSourceManager().getMainFileID() )
                    headerTracker_.enterSourceFile( fileEntry, filename_ );
                else
                    headerTracker_.enterHeader();
            }
            else if ( reason == ExitFile )
            {
                clang::FileID const fileId( exitedFID );
                clang::FileEntry const * const fileEntry( preprocessor_.getSourceManager().getFileEntryForID( fileId ) );
                if ( !fileEntry )
                    return;
                headerTracker_.leaveHeader();
            }
        }

        virtual void EndOfMainFile() override
        {
            headerTracker_.exitSourceFile( headers_ );
        }

        virtual void FileSkipped
        (
            clang::FileEntry const & fileEntry,
            clang::Token const &,
            clang::SrcMgr::CharacteristicKind
        ) LLVM_OVERRIDE
        {
            headerTracker_.headerSkipped();
        }

        virtual void MacroExpands( clang::Token const & macroNameTok, clang::MacroDirective const * md, clang::SourceRange, clang::MacroArgs const * ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
        }

        virtual void MacroDefined( clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroDefined( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void MacroUndefined( clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUndefined( macroNameTok.getIdentifierInfo()->getName(), md );
        }

        virtual void Defined( clang::Token const & macroNameTok, clang::MacroDirective const * md, clang::SourceRange ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
        }

        virtual void Ifdef(clang::SourceLocation loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
            headerTracker_.ifDirective( loc, md != NULL );
        }

        virtual void Ifndef(clang::SourceLocation loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
            headerTracker_.ifDirective( loc, md == 0 );
        }

        virtual void PragmaDirective( clang::SourceLocation loc, clang::PragmaIntroducerKind introducer ) LLVM_OVERRIDE
        {
            clang::Token const token( preprocessor_.LookAhead( 0 ) );
            if ( token.is( clang::tok::identifier ) && token.getIdentifierInfo()->getName() == "once" )
            {
                headerTracker_.pragmaOnce();
            }
        }

        virtual void If( clang::SourceLocation loc, clang::SourceRange conditionRange, bool conditionValue ) LLVM_OVERRIDE
        {
            headerTracker_.ifDirective( loc, conditionValue );
        }

        virtual void Elif( clang::SourceLocation loc, clang::SourceRange conditionRange, bool conditionValue, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.elifDirective( loc, conditionValue );
        }

        virtual void Else( clang::SourceLocation loc, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.elseDirective( loc );
        }

        virtual void Endif( clang::SourceLocation loc, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.endifDirective( loc );
        }

    private:
        HeaderTracker & headerTracker_;
        clang::Preprocessor & preprocessor_;
        llvm::StringRef filename_;
        Headers & headers_;
        HeaderList & missingHeaders_;
    };

    struct MemorizeStatCalls_PreventOpenFile : public clang::MemorizeStatCalls
    {
        // Prevent FileManager, HeaderSearch et al. to open files
        // unexpectedly.
        virtual clang::MemorizeStatCalls::LookupResult
            getStat( char const * path, clang::FileData & fileData, bool isFile,
            int * ) LLVM_OVERRIDE
        {
            return clang::MemorizeStatCalls::getStat( path, fileData, isFile, 0 );
        }
    };
}  // anonymous namespace

clang::TargetOptions * createTargetOptions()
{
    clang::TargetOptions * result = new clang::TargetOptions();
    result->Triple = llvm::sys::getDefaultTargetTriple();
    return result;
}

Preprocessor::Preprocessor( Cache * cache )
    :
    diagID_    ( new clang::DiagnosticIDs() ),
    diagOpts_  ( new clang::DiagnosticOptions() ),
    diagEng_   ( new clang::DiagnosticsEngine( diagID_, &*diagOpts_ ) ),
    ppOpts_    ( new clang::PreprocessorOptions() ),
    langOpts_  ( new clang::LangOptions() ),
    targetOpts_( createTargetOptions() ),
    targetInfo_( clang::TargetInfo::CreateTargetInfo( *diagEng_, &*targetOpts_) ),
    hsOpts_    ( new clang::HeaderSearchOptions() ),
    cache_     ( cache )
{
    diagEng_->setEnableAllWarnings( true );
    hsOpts_->UseBuiltinIncludes = false;
    hsOpts_->UseStandardSystemIncludes = false;
    hsOpts_->UseStandardCXXIncludes = false;
    hsOpts_->Sysroot.clear();
}

namespace
{
    struct DiagnosticConsumer : clang::DiagnosticConsumer
    {
        HeaderTracker & headerTracker_;

        explicit DiagnosticConsumer( HeaderTracker & headerTracker )
            : headerTracker_( headerTracker )
        {
        }

        virtual void HandleDiagnostic(
            clang::DiagnosticsEngine::Level level,
            clang::Diagnostic const & info) 
        {
            if ( info.getID() == clang::diag::warn_pp_undef_identifier )
            {
                // We need to get notifications for identifiers which did not get expanded
                // in order to create consistent cache key paths.
                clang::IdentifierInfo const * identifier( info.getArgIdentifier( 0 ) );
                if ( identifier )
                    headerTracker_.macroUsed( identifier->getName() );
            }
        }
    };
}

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

bool Preprocessor::naivePreprocessing( clang::FileEntry const * mainFileEntry, clang::SourceManager & sourceManager, clang::HeaderSearch & headerSearch, Headers & result )
{
    llvm::MemoryBuffer const * mainFileBuffer = sourceManager.getMemoryBufferForFile( mainFileEntry );
    clang::Token tok;
    std::unordered_set<clang::FileEntry const *> alreadyVisited;

    struct HeaderCtx
    {
        HeaderCtx( Header const & h, clang::Lexer * l, clang::FileEntry const * f )
            : currentHeader( h ), currentLexer( l ), fileEntry( f )
        {
        }

        HeaderCtx( HeaderCtx && other )
            : currentHeader( std::move( other.currentHeader ) ),
            currentLexer( other.currentLexer ),
            fileEntry( other.fileEntry )
        {
            other.currentLexer = 0;
        }

        HeaderCtx & operator=( HeaderCtx && other )
        {
            currentHeader = std::move( other.currentHeader );
            currentLexer = other.currentLexer;
            other.currentLexer = 0;
            fileEntry = other.fileEntry;
            return *this;
        }

        ~HeaderCtx()
        {
            delete currentLexer;
        }

        Header currentHeader;
        clang::Lexer * currentLexer;
        clang::FileEntry const * fileEntry;
        Headers headers;
    };

    std::vector<HeaderCtx> fileStack;
    Header header = 
    {
        Dir( mainFileEntry->getDir()->getName() ),
        HeaderName( mainFileEntry->getName() ),
        ContentEntryPtr(),
        true
    };

    fileStack.push_back
    (
        HeaderCtx
        (
            header,
            new clang::Lexer
            (
                sourceManager.getMainFileID(),
                mainFileBuffer,
                sourceManager,
                langOpts()
            ),
            mainFileEntry
        )
    );

    while ( true )
    {
        clang::Lexer & curLexer( *fileStack.back().currentLexer );
        while ( true )
        {
            bool const eof( curLexer.LexFromRawLexer( tok ) );

            if ( !eof && ( tok.isNot( clang::tok::hash ) || !tok.isAtStartOfLine() ) )
                continue;
            else if ( eof || curLexer.LexFromRawLexer( tok ) )
            {
                HeaderCtx const & headerCtx( fileStack.back() );
                naiveCache.storeHeaders( *headerCtx.fileEntry, headerCtx.headers );
                Headers tmp( std::move( headerCtx.headers ) );
                fileStack.pop_back();
                if ( fileStack.empty() )
                {
                    result.swap( tmp );
                    return true;
                }
                else
                {
                    std::copy( tmp.begin(), tmp.end(), std::inserter( fileStack.back().headers, fileStack.back().headers.begin() ) );
                    break;
                }
            }

            if ( tok.isNot( clang::tok::raw_identifier ) || ( llvm::StringRef( tok.getRawIdentifierData(), tok.getLength() ) != "include" ) )
                continue;

            curLexer.LexIncludeFilename( tok );
            llvm::SmallString<1024> searchPath;
            llvm::SmallString<1024> relativePath;
            if ( tok.isNot( clang::tok::angle_string_literal ) && tok.isNot( clang::tok::string_literal ) )
            {
                for ( HeaderCtx const & headerCtx : fileStack )
                    if ( headerCtx.fileEntry != mainFileEntry )
                        naiveCache.markComplex( *headerCtx.fileEntry );
                return false;
            }
            bool const isAngled = tok.is( clang::tok::angle_string_literal );

            llvm::StringRef fileName( tok.getLiteralData() + 1, tok.getLength() - 2 );
            clang::DirectoryLookup const * curDir( 0 );
            clang::FileEntry const * fileEntry( headerSearch.LookupFile( fileName, true, 0, curDir, 
                fileStack.back().fileEntry, &searchPath, &relativePath, NULL ) );
            if ( !fileEntry || ( alreadyVisited.find( fileEntry ) != alreadyVisited.end() ) )
                continue;

            {
                bool isComplex;
                Headers * cacheHeaders;
                if ( naiveCache.hasEntry( *fileEntry, isComplex, cacheHeaders ) )
                {
                    if ( isComplex )
                    {
                        for ( HeaderCtx const & headerCtx : fileStack )
                            if ( headerCtx.fileEntry != mainFileEntry )
                                naiveCache.markComplex( *headerCtx.fileEntry );
                        return false;
                    }
                    else
                    {
                        std::copy( cacheHeaders->begin(), cacheHeaders->end(), std::inserter( fileStack.back().headers, fileStack.back().headers.begin() ) );
                        continue;
                    }
                }
            }

            Dir dir;
            HeaderName headerName;

            bool const relativeToParent( !isAngled && ( fileStack.back().fileEntry->getDir()->getName() == searchPath ) );
            if ( relativeToParent )
            {
                dir =  Dir( fileStack.back().currentHeader.dir );
                llvm::StringRef const parentFilename = fileStack.back().currentHeader.name.get();
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

            ContentEntryPtr contentEntry = ContentCache::singleton().getOrCreate( sourceManager.getFileManager(), fileEntry, NULL );
            clang::FileID id = sourceManager.createFileID( fileEntry, tok.getLocation(), tok.is( clang::tok::string_literal ) ? clang::SrcMgr::C_User : clang::SrcMgr::C_System );

            Header header = {
                dir,
                headerName,
                contentEntry,
                relativeToParent
            };

            fileStack.push_back
            (
                HeaderCtx
                ( 
                    header,
                    new clang::Lexer
                    (
                        id,
                        contentEntry->buffer.get(),
                        sourceManager,
                        langOpts()
                    ),
                    fileEntry
                )
            );
            alreadyVisited.insert( fileEntry );
            break;
        }
    }
    // Never reached.
    return false;
}

bool Preprocessor::scanHeaders( PreprocessingContext const & ppc, llvm::StringRef fileName, Headers & headers, HeaderList & missingHeaders )
{
    // Initialize file manager.
    clang::FileManager fileManager( fsOpts_ );
    fileManager.addStatCache( new MemorizeStatCalls_PreventOpenFile() );

    // Initialize source manager.
    clang::SourceManager sourceManager( *diagEng_, fileManager, false );

    // Setup search path.
    clang::HeaderSearch headerSearch( hsOpts_, sourceManager, *diagEng_, *langOpts_, &*targetInfo_ ) ;
    std::vector<clang::DirectoryLookup> searchPath;
    std::size_t searchPathId( 0 );
    for ( auto const & path : ppc.userSearchPath() )
    {
        clang::DirectoryEntry const * entry = fileManager.getDirectory( path );
        if ( entry )
        {
            llvm::hash_combine( searchPathId, llvm::hash_combine_range( path.begin(), path.end() ) );
            searchPath.push_back( clang::DirectoryLookup( entry, clang::SrcMgr::C_User, false ) );
        }
    }

    for ( auto const & path : ppc.systemSearchPath() )
    {
        clang::DirectoryEntry const * entry = fileManager.getDirectory( path );
        if ( entry )
        {
            llvm::hash_combine( searchPathId, llvm::hash_combine_range( path.begin(), path.end() ) );
            searchPath.push_back( clang::DirectoryLookup( entry, clang::SrcMgr::C_System, false ) );
        }
    }

    headerSearch.SetSearchPaths( searchPath, 0, ppc.userSearchPath().size(), false );

    // Create main file.
    clang::FileEntry const * mainFileEntry = fileManager.getFile( fileName );
    if ( !mainFileEntry )
    {
        std::string error( "Could not find source file '" );
        error.append( fileName.str() );
        error.append( "'." );
        throw std::runtime_error( error );
    }

    assert( !sourceManager.isFileOverridden( mainFileEntry ) );
    sourceManager.overrideFileContents( mainFileEntry,
        prepareSourceFile( fileManager, *mainFileEntry ) );
    sourceManager.createMainFileID( mainFileEntry );

    if ( naivePreprocessing( mainFileEntry, sourceManager, headerSearch, headers ) )
        return true;

    // Do the real preprocessing.
    clang::Preprocessor preprocessor
    (
        ppOpts_,
        *diagEng_,
        langOpts(),
        &*targetInfo_,
        sourceManager,
        headerSearch,
        moduleLoader
    );

    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::value_type const & macro : ppc.defines() )
        macroBuilder.defineMacro( macro.first, macro.second );
    for ( PreprocessingContext::Includes::value_type const & include : ppc.forcedIncludes() )
        macroBuilder.append( llvm::Twine( "#include \"" ) + include + "\"" );
    preprocessor.setPredefines( predefinesStream.str() );
    preprocessor.SetSuppressIncludeNotFoundError( true );
    preprocessor.SetMacroExpansionOnlyInDirectives();

    HeaderTracker headerTracker( preprocessor, searchPathId, cache_ );
    diagEng_->setClient( new DiagnosticConsumer( headerTracker ) );
    struct DiagnosticsSetup
    {
        DiagnosticsSetup( clang::DiagnosticConsumer & client,
            clang::LangOptions const & opts,
            clang::Preprocessor & preprocessor )
            : client_( client )
        {
            client_.BeginSourceFile( opts, &preprocessor );
        }

        ~DiagnosticsSetup() { client_.EndSourceFile(); }

        clang::DiagnosticConsumer & client_;
    } const diagnosticsGuard
    (
        *diagEng_->getClient(),
        langOpts(),
        preprocessor
    );

    preprocessor.addPPCallbacks( new PreprocessorCallbacks( headerTracker, fileName,
        preprocessor, headers, missingHeaders ) );
    
    preprocessor.EnterMainSourceFile();
    if ( diagEng_->hasFatalErrorOccurred() )
        return false;
    while ( true )
    {
        clang::Token token;
        preprocessor.LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    preprocessor.EndSourceFile();
    return true;
}


//------------------------------------------------------------------------------
