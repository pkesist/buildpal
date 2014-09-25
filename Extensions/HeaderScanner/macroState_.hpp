//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef macroState_HPP__051803C3_4ECB_404C_9CCD_74DEF55F53A3
#define macroState_HPP__051803C3_4ECB_404C_9CCD_74DEF55F53A3
//------------------------------------------------------------------------------
#include <unordered_map>

#include <llvm/ADT/SmallString.h>

#include "utility_.hpp"
//------------------------------------------------------------------------------

DEFINE_FLYWEIGHT(llvm::SmallString<64>, MacroName);
DEFINE_FLYWEIGHT(llvm::SmallString<64 + 32>, MacroValue);
typedef std::pair<MacroName, MacroValue> Macro;

extern MacroValue undefinedMacroValue;

class MacroState
{
private:
    typedef std::unordered_map<MacroName, MacroValue> MacroValueMap;

private:
    MacroValueMap macroValueMap_;

private:
    MacroState( MacroState const & ms );
    MacroState & operator=( MacroState const & ms );

public:
    MacroState() {}
    MacroState( MacroState && ms ) :
        macroValueMap_( std::move( ms.macroValueMap_ ) ) {}

    void defineMacro( MacroName const & name, MacroValue const & value )
    {
        macroValueMap_[ name ] = value;
    }

    void undefineMacro( MacroName const & name )
    {
        defineMacro( name, undefinedMacroValue );
    }

    bool getMacroValue( MacroName const & name, MacroValue & value ) const
    {
        MacroValueMap::const_iterator const result = macroValueMap_.find( name );
        if ( result == macroValueMap_.end() )
            return false;
        value = result->second;
        return true;
    }

    MacroValue getMacroValue( MacroName const & name ) const
    {
        MacroValue value;
        return getMacroValue( name, value ) ? value : undefinedMacroValue;
    }

    template <typename F>
    void forEachMacro( F f ) const
    {
        std::for_each( macroValueMap_.begin(), macroValueMap_.end(), f );
    }

    std::size_t size() const { return macroValueMap_.size(); }
};


//------------------------------------------------------------------------------
#endif
