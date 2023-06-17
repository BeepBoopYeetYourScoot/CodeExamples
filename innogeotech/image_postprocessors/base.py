from abc import ABC, abstractmethod
from typing import Union

import ShapeProduct
import ConvertedDetectionProduct
import SimplifiedDetectionProduct


class ImagePostprocessor(ABC):
    ENCODING = 'utf-8'

    @abstractmethod
    def postprocess(
            self, detection_product: ShapeProduct, *args, **kwargs,
    ) -> Union[SimplifiedDetectionProduct, ConvertedDetectionProduct]:
        raise NotImplementedError
