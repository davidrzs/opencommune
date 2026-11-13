from .base import Link, ListingAdapter
from .bern_axioma import BernAxiomaAdapter
from .files_gallery import FilesGalleryAdapter
from .html_links import HtmlLinksAdapter
from .iomedia_api import IomediaApiAdapter
from .mendrisio_legislativo import MendrisioLegislativoAdapter
from .paris_api import ParisApiAdapter
from .sh_cms import ShCmsAdapter
from .skr_files import SkrFilesAdapter
from .wp_media import WpMediaAdapter
from .zug_ratsinfo import ZugRatsinfoAdapter

_REGISTRY: dict[str, ListingAdapter] = {
    HtmlLinksAdapter.name: HtmlLinksAdapter(),
    ParisApiAdapter.name: ParisApiAdapter(),
    ZugRatsinfoAdapter.name: ZugRatsinfoAdapter(),
    WpMediaAdapter.name: WpMediaAdapter(),
    ShCmsAdapter.name: ShCmsAdapter(),
    IomediaApiAdapter.name: IomediaApiAdapter(),
    BernAxiomaAdapter.name: BernAxiomaAdapter(),
    MendrisioLegislativoAdapter.name: MendrisioLegislativoAdapter(),
    SkrFilesAdapter.name: SkrFilesAdapter(),
    FilesGalleryAdapter.name: FilesGalleryAdapter(),
}


def get_adapter(name: str) -> ListingAdapter:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(_REGISTRY)}") from exc


__all__ = [
    "BernAxiomaAdapter",
    "FilesGalleryAdapter",
    "HtmlLinksAdapter",
    "IomediaApiAdapter",
    "Link",
    "ListingAdapter",
    "MendrisioLegislativoAdapter",
    "ParisApiAdapter",
    "ShCmsAdapter",
    "SkrFilesAdapter",
    "WpMediaAdapter",
    "ZugRatsinfoAdapter",
    "get_adapter",
]
