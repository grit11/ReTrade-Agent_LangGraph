# ADR 003：先校验最终回答，阶段事件实时 SSE

SSE 实时发送 stage/domain/tool/handoff；最终回答校验来源和业务结果后以 token(buffered=true) 事件发布。
**本版不是模型逐 Token 直通流。** 避免模型中途决定转交、未校验业务事实或内部工具消息被直接展示。
不把 buffered 回答冒充实时 token。后续如需更低首字延迟，必须设计可撤销候选输出/可信输出门控。

人工咨询和售后审批不同：support 工单只允许 resolve；approval 只允许 approve/reject。
创建 ticket 与 interrupt 位于不同节点；暂停前的创建使用稳定幂等 ID。
interrupt 节点不被通用 try/except 捕获。恢复需管理身份、ticket ID、版本号和处理说明。
同一工单同一处理结论可重试；不同结论冲突。waiting_human 收到普通消息只记入会话，不发 resume。
暂停时新增说明不自动改写已经确认的售后参数；客服必须阅读完整会话，必要时驳回并重新发起。
