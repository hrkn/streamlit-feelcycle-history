import sys

import feelpycle

import feelpycle_proxy

feelpycle_proxy.ensure_installed()

# isort: split
import feelpycle.api

# feelpyclew.api を本物の feelpycle.api モジュールに透過的に差し替え
sys.modules[__name__] = feelpycle.api
