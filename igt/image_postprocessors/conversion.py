from itertools import combinations

import geopandas as gpd
from centerline.geometry import Centerline
from networkx import single_source_dijkstra, Graph
from shapely.geometry import Polygon, MultiLineString

import ImagePostprocessor
import ConvertedDetectionProduct
import SimplifiedDetectionProduct
import ProductStore
import ConversionAlgorithmType
import ImageProductType


class ConversionImagePostprocessor(ImagePostprocessor):
    INTERPOLATION_DISTANCE_DEG = 0.00001
    RIVER_INTERPOLATION_DISTANCE_DEG = 0.0001

    def __init__(self,
                 product_store: ProductStore,
                 conversion_algorithm: ConversionAlgorithmType):
        self.store = product_store
        self.conversion_algorithm = conversion_algorithm
        self.simplified_product = None
        self._is_river = False

    def postprocess(self,
                    simplified_product: SimplifiedDetectionProduct,
                    **kwargs
                    ) -> ConvertedDetectionProduct:
        self.simplified_product = simplified_product
        return self._convert_polygons()

    def _convert_polygons(self) -> ConvertedDetectionProduct:
        assert self.simplified_product, 'No simplified product supplied'

        output_file_path = self.store.new_product_folder(
            self.simplified_product,
            ImageProductType.converted.name)

        gdf = gpd.read_file(self.simplified_product.path,
                            encoding=self.ENCODING)
        if gdf.empty:
            return ConvertedDetectionProduct(output_file_path)
        gdf.geometry = self.conversion_method(gdf.geometry)
        gdf.geometry.reset_index(drop=True, inplace=True)

        gdf.to_file(output_file_path, encoding=self.ENCODING)
        return ConvertedDetectionProduct(output_file_path)

    @property
    def is_river(self):
        return self._is_river

    @is_river.setter
    def is_river(self, value: bool):
        assert isinstance(value, bool)
        self._is_river = value

    @property
    def interpolation_distance(self):
        return (self.INTERPOLATION_DISTANCE_DEG if not self.is_river
                else self.RIVER_INTERPOLATION_DISTANCE_DEG)

    @property
    def conversion_method(self):
        if (self.conversion_algorithm ==
                ConversionAlgorithmType.polygon_to_point):
            return self._convert_polygon_to_centroid
        elif (self.conversion_algorithm ==
              ConversionAlgorithmType.polygon_to_line):
            return self._convert_polygon_to_multiline
        raise ValueError('Unrecognized conversion algorithm')

    @staticmethod
    def _convert_polygon_to_centroid(geometry: gpd.GeoSeries) -> gpd.GeoSeries:
        assert (not len(geometry.index[~geometry.is_valid]))
        return geometry.centroid

    def _convert_polygon_to_multiline(self,
                                      geometry: gpd.GeoSeries
                                      ) -> gpd.GeoSeries:
        assert (not len(geometry.index[~geometry.is_valid]))
        return geometry.map(self.find_center_line)

    def find_center_line(self,
                         polygon: Polygon
                         ) -> MultiLineString:
        """
        Slow bc written with Python-level loops.
        To speed up use numpy arrays instead and search for vectorization.

        Returns: Longest line in the polygon
        """

        voronoi_diagram = Centerline(polygon, self.interpolation_distance)

        graph = Graph()
        edges = [(idx, idx + 1, line.length)
                 for idx, line in enumerate(voronoi_diagram.geoms)]
        graph.add_weighted_edges_from(edges)

        leaf_nodes = [node for node in graph.nodes() if
                      graph.degree[node] == 1]

        shortest_paths = [
            single_source_dijkstra(graph, start_node, end_node)
            for start_node, end_node in combinations(leaf_nodes, 2)
        ]

        max_length = -1
        longest_path = []
        for length, path in shortest_paths:
            if length > max_length:
                max_length = length
                longest_path = path

        center_line_linestrings = [voronoi_diagram.geoms[node]
                                   for node in longest_path[:-1]]
        return MultiLineString(center_line_linestrings)
