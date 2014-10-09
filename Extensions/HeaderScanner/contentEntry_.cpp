#include "contentEntry_.hpp"

namespace
{
    #define BASE 65521UL
    #define NMAX 5552

    #define DO1(buf, i) { sum1 += (buf)[i]; sum2 += sum1; }
    #define DO2(buf, i) DO1(buf, i); DO1(buf, i + 1);
    #define DO4(buf, i) DO2(buf, i); DO2(buf, i + 2);
    #define DO8(buf, i) DO4(buf, i); DO4(buf, i + 4);
    #define DO16(buf) DO8(buf, 0); DO8(buf, 8);
    #define MOD(a) a %= BASE

    std::size_t bsc_adler32( char const * data, std::size_t size )
    {
        unsigned int sum1 = 1;
        unsigned int sum2 = 0;

        while (size >= NMAX)
        {
            for (int i = 0; i < NMAX / 16; ++i)
            {
                DO16(data); data += 16;
            }
            MOD(sum1); MOD(sum2); size -= NMAX;
        }

        while (size >= 16)
        {
            DO16(data); data += 16; size -= 16;
        }

        while (size > 0)
        {
            DO1(data, 0); data += 1; size -= 1;
        }

        MOD(sum1); MOD(sum2);

        return sum1 | (sum2 << 16);
    }


    ////////////////////////////////////////////////////////////////////////////
    //
    // adler32()
    // ---------
    //
    ////////////////////////////////////////////////////////////////////////////

    std::size_t adler32( llvm::MemoryBuffer const * buffer )
    {
        return bsc_adler32( buffer->getBufferStart(), buffer->getBufferSize() );
    }
}


ContentEntry::ContentEntry( llvm::MemoryBuffer * b, llvm::sys::fs::file_status const & stat )
    :
    buffer( b ), checksum( adler32( b ) ), status( stat )
{
}
