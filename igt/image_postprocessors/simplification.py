import geopandas as gpd
import typing
from geopandas import GeoSeries, GeoDataFrame
from itertools import combinations
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.validation import make_valid

from boxkitten.image_postprocessors.base import ImagePostprocessor
from boxkitten.image_postprocessors.orthogonalizer import (
    orthogonalize_buildings)
from boxkitten.image_products import ShapeProduct
from boxkitten.image_products.simplified import SimplifiedDetectionProduct
from boxkitten.product_store import ProductStore
from boxkitten.user_types import ImageProductType


class SimplificationImagePostprocessor(ImagePostprocessor):
    """
    Postprocessor that simplifies the geometry of a given detection product.
    If simplification produces invalid geometry, returns the geometry
    to the initial state
    """
    TOLERANCE_DEG = 0.0001
    BUILDING_TOLERANCE = 0.00002
    SPATIAL_OVERLAY_METHOD = 'difference'
    _CLEAN_GEOMETRY_TYPES = {'Polygon', 'MultiPolygon'}

    def __init__(self,
                 product_store: ProductStore,
                 tolerance_deg: float = TOLERANCE_DEG,
                 ):
        self.store = product_store
        self.detection_product = None
        self.output_file_path = None
        self._is_buildings = False
        self.tolerance = tolerance_deg or self.TOLERANCE_DEG

    @property
    def is_buildings(self) -> bool:
        return self._is_buildings

    @is_buildings.setter
    def is_buildings(self, value: bool) -> None:
        assert isinstance(value, bool), 'Invalid flag value'
        self._is_buildings = value

    def postprocess(self,
                    detection_product: ShapeProduct,
                    tolerance=None,
                    preserve_topology=False,
                    ) -> SimplifiedDetectionProduct:
        if tolerance is None:
            tolerance = self.tolerance
        self.detection_product = detection_product
        self.output_file_path = self.store.new_product_folder(
            self.detection_product,
            ImageProductType.simplified.name)

        if self.is_buildings:
            return self._orthogonalize_detection_product(
                self.BUILDING_TOLERANCE)
        return self._simplify_detection_product(tolerance, preserve_topology)

    def _simplify_detection_product(self,
                                    tolerance,
                                    preserve_topology: bool
                                    ) -> SimplifiedDetectionProduct:
        gdf = gpd.read_file(self.detection_product.path,
                            encoding=self.ENCODING)
        simplified_geometry = gdf.geometry.simplify(
            tolerance, preserve_topology=preserve_topology)

        gdf.geometry = self.make_valid_geometry(simplified_geometry)
        gdf.geometry = self.cleanup(gdf.geometry)

        gdf.to_file(self.output_file_path, encoding=self.ENCODING)
        return SimplifiedDetectionProduct(self.output_file_path)

    def _orthogonalize_detection_product(self,
                                         tolerance,
                                         ) -> SimplifiedDetectionProduct:
        gdf = gpd.read_file(self.detection_product.path,
                            encoding=self.ENCODING)

        gdf.geometry = gdf.geometry.simplify(tolerance, preserve_topology=True)
        gdf.geometry = orthogonalize_buildings(gdf, gdf.crs).geometry
        gdf.geometry = self.make_valid_geometry(gdf.geometry)

        gdf = self._crop_overlapping_geometry(gdf)

        gdf.geometry = self.cleanup(gdf.geometry)

        gdf.to_file(self.output_file_path, encoding=self.ENCODING)
        return SimplifiedDetectionProduct(self.output_file_path)

    def _crop_overlapping_geometry(self,
                                   original_gdf: GeoDataFrame
                                   ) -> GeoDataFrame:
        intersecting_geometry = self._find_intersections(original_gdf.geometry)
        overlaps = GeoDataFrame(geometry=intersecting_geometry,
                                crs=intersecting_geometry.crs)

        if not len(overlaps):
            return original_gdf

        overlaps = self._extract_polygons(overlaps)

        return original_gdf.overlay(overlaps, how=self.SPATIAL_OVERLAY_METHOD)

    @staticmethod
    def _find_intersections(geometry: GeoSeries,
                            combination_count=2) -> GeoSeries:
        """
        Generate all possible combinations of polygons with each other
        Args:
            geometry: GeoSeries of all geometries in GDF
        Returns:
            GeoSeries of intersections
        """
        polygon_combinations = combinations(geometry.tolist(),
                                            combination_count)

        first_poly_idx, second_poly_idx = 0, 1
        return gpd.GeoSeries([
            poly[first_poly_idx].intersection(poly[second_poly_idx])
            for poly in polygon_combinations
            if poly[first_poly_idx].intersects(poly[second_poly_idx])
        ], crs=geometry.crs)

    def _extract_polygons(self, gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Remove all geometry that is not Polygon or Multipolygon.
        We don't need to consider another types at this point (after
        conversion it is not the case)
        Args:
            gdf: GeoSeries of geometries to be cleaned

        Returns: GeoSeries with clean geometry
        """
        return gdf[gdf.geometry.apply(lambda x:
                                      x.type in self._CLEAN_GEOMETRY_TYPES)]

    def make_valid_geometry(self, geometry: GeoSeries):
        return geometry.map(self._make_valid)

    @staticmethod
    def cleanup(geometry: GeoSeries):
        """
        There are 2 emptiness criterion in GPD.
        """
        invalid_geometry_idx, empty_geometry_idx, null_geometry_idx = (
            geometry.index[~geometry.is_valid],
            geometry.index[geometry.is_empty],
            geometry.index[geometry.isna()]
        )
        drop_idx = set(empty_geometry_idx.append(
            null_geometry_idx).append(
            invalid_geometry_idx)
        )

        return geometry.remove(index=drop_idx)

    @staticmethod
    def _make_valid(polygon: Polygon) -> typing.Union[Polygon, MultiPolygon]:
        valid_polygon = make_valid(polygon)
        if isinstance(valid_polygon, (Polygon, MultiPolygon)):
            return valid_polygon
        if isinstance(valid_polygon, GeometryCollection):
            polygons = [poly for poly in valid_polygon.geoms if
                        isinstance(poly, Polygon)]
            multipolygons = [poly for poly in valid_polygon.geoms if
                             isinstance(poly, MultiPolygon)]
            for poly in multipolygons:
                polygons.extend(poly.geoms)
            return MultiPolygon(polygons)

    def remove_holes(self, detection_product: ShapeProduct) -> ShapeProduct:
        gdf = gpd.read_file(detection_product.path, encoding=self.ENCODING)
        gdf.geometry = gdf.geometry.map(self._remove_holes)
        gdf.to_file(detection_product.path, encoding=self.ENCODING)
        return detection_product

    @staticmethod
    def _remove_holes(polygon: typing.Union[Polygon, MultiPolygon]):
        if isinstance(polygon, MultiPolygon):
            return MultiPolygon(Polygon(poly.exterior) for poly in polygon)
        if not polygon.interiors:
            return polygon
        return Polygon(list(polygon.exterior.coords))
