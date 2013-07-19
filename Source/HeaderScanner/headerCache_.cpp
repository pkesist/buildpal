//------------------------------------------------------------------------------
#include "headerCache_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>
//------------------------------------------------------------------------------

clang::FileEntry const * Cache::CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );
    if ( !sourceManager.isFileOverridden( result ) )
    {
        if ( !buffer_ )
        {
            // Cache the result.
            std::string content;
            llvm::raw_string_ostream defineStream( content );
            for ( MacroUsages::const_iterator iter( macroUsages.begin() ); iter != macroUsages.end(); ++iter )
            {
                if ( iter->first == MacroUsage::defined )
                {
                    Macro const & macro( iter->second );
                    assert( macro.second.data() );
                    defineStream << "#define " << macro.second << '\n';
                }

                if ( iter->first == MacroUsage::undefined )
                {
                    Macro const & macro( iter->second );
                    assert( macro.second.data() );
                    defineStream << "#undef " << macro.first << '\n';
                }
            }
            defineStream << '\0';
            buffer_.reset( llvm::MemoryBuffer::getMemBufferCopy( defineStream.str(), "" ) );
        }

        sourceManager.overrideFileContents( result, buffer_.get(), false );
    }
    return result;
}

std::string Cache::uniqueFileName()
{
    std::stringstream result;
    result << "__cached_file_" << ++counter_;
    return result.str();
}


void Cache::CacheEntry::releaseFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );
    assert( result );
    sourceManager.disableFileContentsOverride( result );
}

Cache::CacheHit * Cache::findEntry( llvm::StringRef fileName, clang::Preprocessor const & preprocessor )
{
    // Shared ownership.
    boost::shared_lock<boost::shared_mutex> const lock( sharedMutex_ );
    HeadersInfo::iterator const iter( headersInfo().find( fileName ) );
    if ( iter != headersInfo().end() )
        return iter->second.find( preprocessor );
    return 0;
}

Cache::CacheHit * Cache::HeaderInfo::find( clang::Preprocessor const & preprocessor )
{
    if ( disable_ )
        return 0;

    for
    (
        Base::iterator headerInfoIter( Base::begin() );
        headerInfoIter != Base::end();
        ++headerInfoIter
    )
    {
        Macros const & inputMacros( headerInfoIter->first );
        bool isMatch( true );

        struct MacroIsNotCurrent
        {
            clang::Preprocessor const & pp_;
            
            explicit MacroIsNotCurrent( clang::Preprocessor const & pp ) : pp_( pp ) {}

            bool operator()( Macro const & macro )
            {
                return macro.second != macroDefFromSourceLocation( pp_,
                    pp_.getMacroDirective( pp_.getIdentifierInfo( macro.first ) ) );
            }
        } macroIsNotCurrent( preprocessor );
        
        if
        (
            std::find_if
            (
                inputMacros.begin(), inputMacros.end(),
                macroIsNotCurrent
            ) != inputMacros.end()
        )
            continue;

        return &*headerInfoIter;
    }
    return 0;
}

void Cache::HeaderInfo::insert( Macros const & key, CacheEntry const & value )
{
    Base::insert( std::make_pair( key, value ) );
}


//------------------------------------------------------------------------------
