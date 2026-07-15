// Native storage backend for World.terrain — R8 slice 2, the first
// module that ports actual object-graph STORAGE rather than an
// isolated pure function. Deliberately narrow: this class only holds
// flat elevation/biome arrays and answers get/set queries by (x, y).
// It knows nothing about Tile, Biome, rivers, lakes, agents, or any
// other object — the Python-side `TerrainGrid`/`TerrainRow` wrapper
// (world/terrain.py) is what makes this behave like the
// `list[list[Tile]]` every existing call site already expects
// (`terrain[y][x]`, `terrain[y][x] = Tile(...)`, `len(terrain)`,
// `for row in terrain: for tile in row`), so none of the ~60+
// subscript/mutation/iteration call sites across the codebase needed
// to change. Biome is stored as a plain int index into `list(Biome)`
// (Python's own enum declaration order, all 9 members including
// RIVER — unlike climate_drift.cpp's BIOME_ORDER-only 8-value scheme,
// which deliberately excludes RIVER since climate drift never touches
// river tiles; this storage layer needs to hold every possible biome
// a tile can be) — Python converts both ways at the wrapper boundary,
// same "resolve enums in Python, hand C++ only plain data" pattern
// climate_drift.cpp established as the only precedent for a Biome
// value crossing the boundary at all.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <stdexcept>
#include <vector>

namespace py = pybind11;

namespace {

class NativeTerrainGrid {
public:
    NativeTerrainGrid(int width, int height)
        : width_(width), height_(height),
          elevation_(static_cast<size_t>(width) * height, 0.0),
          biome_(static_cast<size_t>(width) * height, 0) {
        if (width <= 0 || height <= 0) throw std::invalid_argument("width/height must be positive");
    }

    int width() const { return width_; }
    int height() const { return height_; }

    double get_elevation(int x, int y) const { return elevation_[index(x, y)]; }
    int get_biome(int x, int y) const { return biome_[index(x, y)]; }

    void set_tile(int x, int y, double elevation, int biome) {
        size_t i = index(x, y);
        elevation_[i] = elevation;
        biome_[i] = biome;
    }

    // Bulk access for World.to_dict()/from_dict() — one call instead
    // of width*height individual get/set calls at the (de)serialization
    // boundary, where every tile is touched at once anyway.
    std::vector<double> elevation_flat() const { return elevation_; }
    std::vector<int> biome_flat() const { return biome_; }

    void load_flat(const std::vector<double> &elevation, const std::vector<int> &biome) {
        size_t expected = static_cast<size_t>(width_) * height_;
        if (elevation.size() != expected || biome.size() != expected) {
            throw std::invalid_argument("load_flat: array size doesn't match width*height");
        }
        elevation_ = elevation;
        biome_ = biome;
    }

private:
    size_t index(int x, int y) const {
        return static_cast<size_t>(y) * width_ + x;
    }

    int width_, height_;
    std::vector<double> elevation_;
    std::vector<int> biome_;
};

}  // namespace

void register_terrain_grid(py::module_ &m) {
    py::class_<NativeTerrainGrid>(m, "TerrainGrid")
        .def(py::init<int, int>(), py::arg("width"), py::arg("height"))
        .def_property_readonly("width", &NativeTerrainGrid::width)
        .def_property_readonly("height", &NativeTerrainGrid::height)
        .def("get_elevation", &NativeTerrainGrid::get_elevation, py::arg("x"), py::arg("y"))
        .def("get_biome", &NativeTerrainGrid::get_biome, py::arg("x"), py::arg("y"))
        .def("set_tile", &NativeTerrainGrid::set_tile,
             py::arg("x"), py::arg("y"), py::arg("elevation"), py::arg("biome"))
        .def("elevation_flat", &NativeTerrainGrid::elevation_flat)
        .def("biome_flat", &NativeTerrainGrid::biome_flat)
        .def("load_flat", &NativeTerrainGrid::load_flat, py::arg("elevation"), py::arg("biome"),
             "Bulk-replace all tile data at once, row-major (y*width+x) — "
             "used by TerrainGrid.from_nested for fast deserialization.");
}
