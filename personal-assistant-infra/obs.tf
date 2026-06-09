# OBS Bucket — Web Chat 前端静态托管
#
# 等价于原 CDKTF stacks/pa-stack.ts 中的 ObsBucket 资源。
# 配置：public-read ACL, versioning 启用, SPA 静态网站托管（error_document → index.html）

resource "huaweicloud_obs_bucket" "web_chat" {
  bucket     = "personal-assistant-web-chat"
  acl        = "public-read"
  versioning = true

  website {
    index_document = "index.html"
    error_document = "index.html" # SPA fallback: 所有路由返回 index.html
  }
}
