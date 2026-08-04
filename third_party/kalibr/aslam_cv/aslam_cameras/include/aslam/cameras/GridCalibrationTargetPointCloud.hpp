#ifndef ASLAM_GRID_CALIBRATION_TARGET_PointCloud_HPP
#define ASLAM_GRID_CALIBRATION_TARGET_PointCloud_HPP

#include <vector>
#include <Eigen/Core>
#include <opencv2/core/core.hpp>
#include <boost/shared_ptr.hpp>
#include <boost/serialization/export.hpp>
#include <sm/assert_macros.hpp>
#include <sm/boost/serialization.hpp>
#include <aslam/cameras/GridCalibrationTargetBase.hpp>

namespace aslam {
namespace cameras {

class GridCalibrationTargetPointCloud : public GridCalibrationTargetBase {
 public:
  SM_DEFINE_EXCEPTION(Exception, std::runtime_error);

  typedef boost::shared_ptr<GridCalibrationTargetPointCloud> Ptr;
  typedef boost::shared_ptr<const GridCalibrationTargetPointCloud> ConstPtr;

  //target extraction options. TODO might not need
  struct PointCloudOptions {
    PointCloudOptions() {};

    /// \brief Serialization support
    enum {CLASS_SERIALIZATION_VERSION = 1};
    BOOST_SERIALIZATION_SPLIT_MEMBER()
    template<class Archive>
    void save(Archive & ar, const unsigned int /*version*/) const {}
    template<class Archive>
    void load(Archive & ar, const unsigned int /*version*/) {}
  };

  /// \brief initialize from points matrix
  GridCalibrationTargetPointCloud(const Eigen::MatrixXd &pointsMat,
                                    const GridCalibrationTargetPointCloud::PointCloudOptions &options = PointCloudOptions());

  virtual ~GridCalibrationTargetPointCloud() {};

  /// \brief extract the calibration target points from an image and write to an observation
  bool computeObservation(const cv::Mat &image, Eigen::MatrixXd &outImagePoints,
                          std::vector<bool> &outCornerObserved) const;

 private:
  /// \brief 3D points extraction options
  PointCloudOptions _options;

  ///////////////////////////////////////////////////
  // Serialization support
  ///////////////////////////////////////////////////
 public:
  enum {CLASS_SERIALIZATION_VERSION = 1};
  BOOST_SERIALIZATION_SPLIT_MEMBER()

  //serialization ctor
  GridCalibrationTargetPointCloud() {};

 protected:
  friend class boost::serialization::access;

  template<class Archive>
  void save(Archive & ar, const unsigned int /* version */) const {
    boost::serialization::void_cast_register<GridCalibrationTargetPointCloud, GridCalibrationTargetBase>(
          static_cast<GridCalibrationTargetPointCloud *>(NULL),
          static_cast<GridCalibrationTargetBase *>(NULL));
    ar << BOOST_SERIALIZATION_BASE_OBJECT_NVP(GridCalibrationTargetBase);
    ar << BOOST_SERIALIZATION_NVP(_options);
  }
  template<class Archive>
  void load(Archive & ar, const unsigned int /* version */) {
    boost::serialization::void_cast_register<GridCalibrationTargetPointCloud, GridCalibrationTargetBase>(
          static_cast<GridCalibrationTargetPointCloud *>(NULL),
          static_cast<GridCalibrationTargetBase *>(NULL));
    ar >> BOOST_SERIALIZATION_BASE_OBJECT_NVP(GridCalibrationTargetBase);
    ar >> BOOST_SERIALIZATION_NVP(_options);
  }
};

}  // namespace cameras
}  // namespace aslam

SM_BOOST_CLASS_VERSION(aslam::cameras::GridCalibrationTargetPointCloud);
SM_BOOST_CLASS_VERSION(aslam::cameras::GridCalibrationTargetPointCloud::PointCloudOptions);
BOOST_CLASS_EXPORT_KEY(aslam::cameras::GridCalibrationTargetPointCloud);

#endif /* ASLAM_GRID_CALIBRATION_TARGET_PointCloud_HPP */
