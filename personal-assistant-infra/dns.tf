# DNS — CNAME 记录
#
# 将 chat.resource-governance.cloud CNAME 到 OBS 静态网站 endpoint，
# 解决 OBS 默认域名强制 Content-Disposition: attachment 的问题。
#
# 域名在华为云购买时已自动创建 Zone，需先 import 再 apply。

resource "huaweicloud_dns_zone" "main" {
  name        = "resource-governance.cloud"
  description = "Personal Assistant 主域名"
  zone_type   = "public"
}

# CNAME: chat.resource-governance.cloud → OBS website endpoint
resource "huaweicloud_dns_recordset" "chat" {
  zone_id     = huaweicloud_dns_zone.main.id
  name        = "chat.resource-governance.cloud."
  type        = "CNAME"
  ttl         = 300
  records     = ["${huaweicloud_obs_bucket.web_chat.bucket}.obs-website.${var.region}.myhuaweicloud.com."]
  description = "Web Chat 前端入口 → OBS 静态网站"
}
