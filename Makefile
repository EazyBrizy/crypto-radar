.PHONY: smoke-virtual

smoke-virtual:
	powershell -ExecutionPolicy Bypass -File ./scripts/smoke_virtual.ps1
