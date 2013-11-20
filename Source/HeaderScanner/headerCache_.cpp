//------------------------------------------------------------------------------
#include "headerCache_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/spirit/include/karma.hpp>

#include <iostream>
//------------------------------------------------------------------------------

clang::FileEntry const * CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, 0, 0 ) );

    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, memoryBuffer_.get(), true );
    return result;
}

void CacheEntry::generateContent( std::recursive_mutex & generateContentMutex )
{
    // Strictly speaking, this should be tested with lock held.
    // However, that is expensive, and in the worst case we
    // will get a false negative and generate content
    // redundantly.
    if ( memoryBuffer_ )
        return;

    struct GenerateContent
    {
        typedef void result_type;

        GenerateContent( llvm::raw_string_ostream & ostream, std::recursive_mutex & generateContentMutex )
            : ostream_( ostream ), generateContentMutex_( generateContentMutex ) {}

        void operator()( MacroWithUsage const & mwu )
        {
            if ( mwu.first == MacroUsage::defined )
            {
                ostream_ << "#define " << macroName( mwu.second ) << macroValue( mwu.second ) << '\n';
            }
            else
            {
                assert( mwu.first == MacroUsage::undefined );
                ostream_ << "#undef " << macroName( mwu.second ) << '\n';
            }
        }

        void operator()( CacheEntryPtr const & ce )
        {
            if ( !ce->memoryBuffer_ )
                ce->generateContent( generateContentMutex_ );
            ostream_ << ce->buffer_;
        }

        llvm::raw_string_ostream & ostream_;
        std::recursive_mutex & generateContentMutex_;
    };
    
    std::string tmpBuf;
    llvm::raw_string_ostream defineStream( tmpBuf );
    GenerateContent contentGenerator( defineStream, generateContentMutex );
    std::for_each( headerContent().begin(), headerContent().end(),
        [&]( HeaderEntry const & he ) { boost::apply_visitor( contentGenerator, he ); } );
    defineStream << '\0';
    defineStream.flush();
    std::unique_lock<std::recursive_mutex> const generateContentLock( generateContentMutex );
    buffer_.swap( tmpBuf );
    memoryBuffer_.reset( llvm::MemoryBuffer::getMemBuffer( buffer_, "", true ) );
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

CacheEntryPtr Cache::findEntry( llvm::StringRef fileName, MacroState const & macroState )
{
    unsigned const uid( getFileId( fileName ) );
    std::vector<CacheEntryPtr> entriesForUid;
    {
        std::unique_lock<std::mutex> const lock( cacheMutex_ );
        std::pair<CacheContainer::iterator, CacheContainer::iterator> const iterRange =
            cacheContainer_.equal_range( uid );
        std::copy( iterRange.first, iterRange.second, std::back_inserter( entriesForUid ) );
    }

    for ( CacheEntryPtr pEntry : entriesForUid )
    {
        if
        (
            std::find_if_not
            (
                pEntry->usedMacros().begin(),
                pEntry->usedMacros().end(),
                [&]( Macro const & macro )
                {
                    MacroState::const_iterator const iter( macroState.find( macroName( macro ) ) );
                    llvm::StringRef const value( macroValue( macro ) );
                    return iter == macroState.end()
                        ? isUndefinedMacroValue( value )
                        : iter->getValue() == value
                    ;
                }
            ) == pEntry->usedMacros().end()
        )
        {
            ++hits_;
            pEntry->generateContent( generateContentMutex_ );
            //cacheContainer_.modify( iter, []( CacheEntryPtr p ) { p->incHitCount(); } );
            return pEntry;
        }
    }
    ++misses_;
    return CacheEntryPtr();
}


//------------------------------------------------------------------------------
