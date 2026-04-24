' EGM Downloader launcher — runs Python completely hidden (no console flash)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the folder this .vbs is in
folder = fso.GetParentFolderName(WScript.ScriptFullName)

' Try python, then python3
For Each py In Array("python", "python3")
    On Error Resume Next
    ret = sh.Run("""" & py & """ """ & folder & "\launch.py""", 0, False)
    If Err.Number = 0 Then WScript.Quit
    On Error GoTo 0
Next

' Python not found
MsgBox "Python 3.10+ is required." & vbCrLf & vbCrLf & _
       "Download from: https://python.org" & vbCrLf & _
       "Check 'Add Python to PATH' during install.", _
       16, "EGM Downloader"
