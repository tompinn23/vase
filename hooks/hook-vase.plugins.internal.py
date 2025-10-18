from PyInstaller.utils.hooks import collect_submodules, collect_data_files
hiddenimports = collect_submodules("vase.plugins.internal")
datas = collect_data_files("vase.plugins.internal")