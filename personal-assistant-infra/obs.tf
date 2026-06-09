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

# 🔧 自定义域名绑定不支持 Terraform，需手动在 OBS 控制台操作：
#   控制台 → OBS → personal-assistant-web-chat → 域名管理 → 绑定用户域名
#   输入: chat.resource-governance.cloud
