#import "driver/template.typ": driver_page
#let title = "Metadata"
#let post_subtitle = {{POST_SUBTITLE}}

#show: driver_page.with(title: title)

*Post Title:* {{POST_TITLE}} \
#if post_subtitle != none [
  *Post Subtitle:* #post_subtitle \
]
*Publish Date:* {{PUBLISH_DATE}} \
*Revision:* {{REVISION}} \
*Workspace Name:* {{WORKSPACE_NAME}} \
*Post Path:* {{POST_PATH}} \
*Source File Count:* {{SOURCE_FILE_COUNT}} \
*Source Hash:* {{SOURCE_HASH}} \
*PDF Asset:* {{PDF_ASSET}} \
*Generated At:* {{GENERATED_AT}} \

= Source Files

{{SOURCE_FILES}}
