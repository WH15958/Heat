---
name: "dll-analyzer"
description: "Analyzes DLL files including exports, dependencies, PE headers, and .NET assemblies. Invoke when user needs to analyze or inspect DLL files."
---

# DLL Analyzer

This skill provides comprehensive analysis capabilities for Windows DLL (Dynamic Link Library) files.

## Features

### 1. Export Functions Analysis
List all exported functions from a DLL with their names, ordinals, and addresses.

### 2. Dependency Analysis
Identify all DLL dependencies and imports required by the target DLL.

### 3. PE Header Analysis
Extract PE (Portable Executable) header information including:
- Machine type (x86, x64, ARM, etc.)
- Timestamp
- Sections information
- Entry point
- DLL characteristics

### 4. .NET Assembly Analysis
For .NET DLLs, analyze:
- Assembly information
- Types and namespaces
- Methods and properties
- References

## Usage

When the user wants to analyze a DLL file:

1. **Ask for the DLL path** - Get the absolute path to the DLL file from the user
2. **Determine analysis type** - Ask what kind of analysis is needed:
   - Exports only
   - Dependencies only
   - Full PE analysis
   - .NET assembly analysis (for .NET DLLs)
3. **Run appropriate commands** - Use the tools below based on analysis type

## Tools and Commands

### Using dumpbin (Windows SDK)
```powershell
# List exports
dumpbin /EXPORTS path\to\file.dll

# List imports/dependencies
dumpbin /IMPORTS path\to\file.dll

# Full PE header info
dumpbin /HEADERS path\to\file.dll

# All information
dumpbin /ALL path\to\file.dll
```

### Using PowerShell
```powershell
# Get basic file info
Get-Item path\to\file.dll | Format-List *

# Read PE header using .NET
[System.Reflection.Assembly]::LoadFile("path\to\file.dll")
```

### Using Python pefile (if available)
```python
import pefile
pe = pefile.PE("path/to/file.dll")
print(pe.dump_info())
```

### For .NET Assemblies
```powershell
# Using ildasm (if available)
ildasm path\to\file.dll /out=output.il

# Using PowerShell reflection
[System.Reflection.Assembly]::LoadFrom("path\to\file.dll").GetTypes()
```

## Workflow

1. Verify the DLL file exists at the provided path
2. Check if it's a valid PE/DLL file
3. Determine if it's a .NET assembly or native DLL
4. Run the appropriate analysis based on user needs
5. Present results in a readable format

## Notes

- dumpbin requires Visual Studio or Windows SDK to be installed
- For .NET DLLs, prefer reflection-based analysis when possible
- Some analysis may require administrator privileges
- Handle 32-bit vs 64-bit DLLs appropriately
