//------------------------------------------------------------------------------
#include "headerCache_.hpp"
#include "headerTracker_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/spirit/include/karma.hpp>

#include <iostream>
//------------------------------------------------------------------------------

clang::FileEntry const * CacheEntry::getFileEntry( clang::SourceManager & sourceManager, std::recursive_mutex & generateContentMutex )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, 0, 0 ) );
    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, cachedContent( generateContentMutex ), true );
    return result;
}

llvm::MemoryBuffer const * CacheEntry::cachedContent( std::recursive_mutex & generateContentMutex )
{
    if ( !memoryBuffer_ )
    {
        std::string tmp;
        generateContent( tmp );

        {
            std::unique_lock<std::recursive_mutex> const generateContentLock( generateContentMutex );
            buffer_.swap( tmp );
            memoryBuffer_.reset( llvm::MemoryBuffer::getMemBuffer( buffer_, "", true ) );
            // We no longer need header content.
            //HeaderContent dummy( 0 );
            //headerContent().swap( dummy );
        }
    }
    return memoryBuffer_.get();
}

void CacheEntry::generateContent( std::string & buffer )
{
    llvm::raw_string_ostream defineStream( buffer );
    std::for_each(
        headerContent().begin(),
        headerContent().end(),
        [&]( HeaderEntry const & he )
        {
            switch ( he.first )
            {
            case MacroUsage::defined:
                defineStream << "#define " << macroName( he.second ) << macroValue( he.second ) << '\n';
                break;
            case MacroUsage::undefined:
                defineStream << "#undef " << macroName( he.second ) << '\n';
                break;
            }
        }
    );
    defineStream << '\0';
    defineStream.flush();
}

std::string Cache::uniqueFileName()
{
    std::string result;
    using namespace boost::spirit::karma;
    generate( std::back_inserter( result ),
        lit( "__cached_file_" ) << uint_,
        ++counter_ );
    return result;
}

CacheEntryPtr Cache::findEntry( llvm::StringRef fileName, HeaderCtx const & headerCtx )
{
    unsigned const uid( getFileId( fileName ) );
    std::vector<CacheEntryPtr> entriesForUid;
    {
        std::unique_lock<std::mutex> const lock( cacheMutex_ );
        std::pair<CacheContainer::iterator, CacheContainer::iterator> const iterRange =
            cacheContainer_.equal_range( uid );
        std::copy( iterRange.first, iterRange.second, std::back_inserter( entriesForUid ) );
    }

    struct MacroMatchesState
    {
        explicit MacroMatchesState( HeaderCtx const & headerCtx ) : headerCtx_( headerCtx ) {}

        bool operator()( Macro const & macro ) const
        {
            return headerCtx_.getMacroValue( macroName( macro ) ) == macroValue( macro );
        }

        HeaderCtx const & headerCtx_;
    };

    for ( CacheEntryPtr pEntry : entriesForUid )
    {
        if
        (
            std::find_if_not
            (
                pEntry->usedMacros().begin(),
                pEntry->usedMacros().end(),
                MacroMatchesState( headerCtx )
            ) == pEntry->usedMacros().end()
        )
        {
            ++hits_;
            std::unique_lock<std::mutex> const lock( cacheMutex_ );
            CacheContainer::index<ById>::type::iterator const iter = cacheContainer_.get<ById>().find( &*pEntry );
            cacheContainer_.get<ById>().modify( iter, []( CacheEntryPtr p ) { p->incHitCount(); } );
            return pEntry;
        }
    }
    ++misses_;
    return CacheEntryPtr();
}


//------------------------------------------------------------------------------
