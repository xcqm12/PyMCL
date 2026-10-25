@echo off
rem PyMCL 打包脚本：生成 Logo -> PyInstaller 打包为单文件 exe
cd /d %~dp0

echo [1/3] 生成 Logo 与图标...
python tools\gen_logo.py
if errorlevel 1 goto fail

echo [2/3] 运行 PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed --clean ^
  --name PyMCL ^
  --icon assets\logo.ico ^
  --add-data "assets;assets" ^
  main.py
if errorlevel 1 goto fail

echo [3/3] 完成！
echo 输出文件: dist\PyMCL.exe
goto end

:fail
echo 打包失败，请检查上方错误信息。
exit /b 1

:end
