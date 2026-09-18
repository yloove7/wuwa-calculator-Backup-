#include <algorithm>
#include <cmath>
#include <tuple>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

using Component = std::tuple<int, int, int, int, double>;
using Event = std::tuple<long long, int, int>;

struct Group {
    std::vector<Component> items;
};

std::vector<Event> group_damage_components(
    std::vector<Component> components,
    int frame_width,
    int frame_height
) {
    std::sort(components.begin(), components.end(), [](const Component& left, const Component& right) {
        return std::tie(std::get<1>(left), std::get<0>(left)) <
               std::tie(std::get<1>(right), std::get<0>(right));
    });

    std::vector<Group> groups;
    for (const auto& component : components) {
        const int x = std::get<0>(component);
        const int y = std::get<1>(component);
        const int height = std::get<3>(component);
        const double center_y = y + height / 2.0;

        if (!groups.empty()) {
            Group& group = groups.back();
            double group_center_y = 0.0;
            int group_right = 0;
            for (const auto& item : group.items) {
                group_center_y += std::get<1>(item) + std::get<3>(item) / 2.0;
                group_right = std::max(group_right, std::get<0>(item) + std::get<2>(item));
            }
            group_center_y /= static_cast<double>(group.items.size());
            if (std::abs(center_y - group_center_y) <= std::max(12.0, height * 0.7) &&
                x <= group_right + 28) {
                group.items.push_back(component);
                continue;
            }
        }
        groups.push_back(Group{{component}});
    }

    std::vector<Event> events;
    for (const auto& group : groups) {
        int left = std::get<0>(group.items.front());
        int right = left + std::get<2>(group.items.front());
        int top = std::get<1>(group.items.front());
        int bottom = top + std::get<3>(group.items.front());
        double filled_area = 0.0;
        for (const auto& item : group.items) {
            left = std::min(left, std::get<0>(item));
            right = std::max(right, std::get<0>(item) + std::get<2>(item));
            top = std::min(top, std::get<1>(item));
            bottom = std::max(bottom, std::get<1>(item) + std::get<3>(item));
            filled_area += std::get<4>(item);
        }
        const int group_width = right - left;
        const int group_height = bottom - top;
        if (group.items.size() < 2 && group_width < 16) {
            continue;
        }
        const double density = std::min(1.0, filled_area / std::max(1, group_width * group_height));
        const auto estimated = static_cast<long long>(std::min(
            9999999999.0,
            std::max(100.0, group_width * group_height * (1.0 + density))
        ));
        events.emplace_back(
            estimated,
            static_cast<int>(frame_width * 0.10 + (left + right) / 2.0),
            static_cast<int>(frame_height * 0.05 + (top + bottom) / 2.0)
        );
    }
    return events;
}

PYBIND11_MODULE(_tethys_native, module) {
    module.doc() = "Optional native helpers for Tethys damage analysis";
    module.def(
        "group_damage_components",
        &group_damage_components,
        py::arg("components"),
        py::arg("frame_width"),
        py::arg("frame_height")
    );
}