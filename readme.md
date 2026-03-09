**ChronoName — A Deterministic Workflow for Renaming Photos by Capture Time**

After building *DedupTool* to safely remove duplicate photos, another recurring problem in large photo libraries became obvious: filenames.

Anyone who keeps photos for many years eventually runs into the same situation. Different cameras, phones, and software all create their own naming conventions , such as IMG\_4321.JPG, PXL\_20240118\_103806764.MP4 or DSC00987.ARW.

These names are not very helpful when synchronizing files coming from multiple devices.

When files from different devices and years end up in the same archive, filenames quickly stop being useful. What you really want is the *capture time*.

Fortunately, that information usually exists in the metadata. Turning it into reliable filenames across thousands of files, however, is harder than it looks.

At first glance renaming photos by capture time seems straightforward: read the EXIF timestamp and format the filename. In practice things quickly become messy because different devices store timestamps differently. Typical examples include: still images using *EXIF DateTimeOriginal,* videos using *QuickTime CreateDate***,** timestamps stored *without timezone information,* videos stored *in UTC***,** exported or edited files with altered metadata and files with broken or placeholder timestamps.

If these timestamps are interpreted incorrectly, chronological ordering breaks. A photo and a video captured at the same moment might suddenly appear hours apart.

To solve this I built a small utility called *ChronoName*. This script automates the well-known metadata utility [*ExifTool*](https://exiftool.org/)and adds a safe workflow layer around it.

The idea is simple: apply a deterministic timestamp policy and safely rename files based on capture time. ChronoName generates filenames using a deterministic format with the bracketed components optionally, used only when necessary to distinguish between files: *YYYYMMDD\_HHMMSS[\_milliseconds][\_\_DEVICE][\_counter].ext*.

| Naming Examples 
| 20240118\_173839.jpg                  | this is the default |
| 20240118\_173839\_234.jpg             | a trailing counter is added when several files share the same creation time |
| 20240118\_173839\_\_SONY-A7M3.arw     | maker-model information can be added if requested |

Designing the renaming workflow turned out to be more interesting than expected. The most important aspects were not parsing metadata but ensuring that the process is *safe and predictable*. *Dry-run mode*(--dry-run) shows you the planned changes without actually changing any files.

ChronoName also creates undo logs. Each run writes a log file: *rename\_log\_XXXXXXXX.json*. This log records every rename operation and allows a full rollback. Starting ChronoName again with the added argument: --undo rename\_log\_xxxxxxxx.json undoes the previous renaming. This makes the process fully reversible.

An optional collection manifests describing the resulting archive state

The result is a workflow that is *deterministic, reversible, and auditable*.

ChronoName is meant to work alongside DedupTool. ChronoName normalize filenames, DedupTool remove redundant copies. Together they form a simple workflow for cleaning up large photo libraries.

I wrote a full breakdown of the design and implementation here: <https://code2trade.dev/chrononame-a-deterministic-workflow-for-renaming-photos-by-capture-time/>