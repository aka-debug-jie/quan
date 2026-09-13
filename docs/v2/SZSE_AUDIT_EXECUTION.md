# 深市审计执行方式

当前用户回传的第五批结果：8093 个缺失日已解释 4522 日，剩余 3571 日、123 个区间。第六批尚未在受限环境复算。

为减少逐批 sudo 操作，使用 scripts/v2/export_szse_matching_dates.py 一次性输出固定月报报告中的 8093 行证券代码、缺失日期、月报分类。脚本使用系统 Python 标准库，固定源 SHA-256，固定预期计数，按字段白名单重建输出。没有原始行情、证据正文或任意路径参数，不修改源权限；输出重定向由普通用户 shell 执行。

该导出明确释放缺失日期标签用于本地补证。普通账户随后完成证据核验和全部日期匹配，输出仅作本地诊断，gap 与 membership gate 保持 BLOCKED_DATA。完成后统一在 sealed 环境复算，正式结论以该次结果为准。若免费官方证据仍不足，如实保留残余。

未启用的桥接草案：szse_audit_bridge.py、build_szse_audit_bridge.py、szse_bridge_start_template.py、szse_bridge_seal.py。安全复核发现证据信任锚、PDF 解析隔离和临时 UID 响应持久化边界未闭合，不得部署。未生成启动包装器，未启动服务，未改 sudoers 或原始数据权限。草案保留供追踪，不作为交付入口。

验证：此前完整离线 pytest 306 passed，Ruff/格式/mypy 通过；新增导出脚本 Ruff/格式、合成 8093 行字段白名单、计数、哈希拒绝及 gate 保持检查通过。尚未读取真实受限报告，真实导出计数由脚本执行时校验。
