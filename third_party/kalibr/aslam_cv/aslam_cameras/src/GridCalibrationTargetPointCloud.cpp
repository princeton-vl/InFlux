#include <vector>
#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/calib3d/calib3d.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <aslam/cameras/GridCalibrationTargetPointCloud.hpp>
#include <sm/eigen/serialization.hpp>

namespace aslam {
namespace cameras {

/// \brief Construct a calibration target of points in 3D space
///        pointsMat: matrix of point coordinates in the point cloud
GridCalibrationTargetPointCloud::GridCalibrationTargetPointCloud(
    const Eigen::MatrixXd &pointsMat,
    const PointCloudOptions &options)
    : GridCalibrationTargetBase(1, pointsMat.rows()),
      _options(options)
    {
      _points = pointsMat; // copy. TODO in future could std::move
    }

/// \brief extract the calibration target points from an image and write to an observation
bool GridCalibrationTargetPointCloud::computeObservation(const cv::Mat & image,
           Eigen::MatrixXd & outImagePoints, std::vector<bool> &outCornerObserved) const
  {
  SM_ASSERT_TRUE(Exception, true, "GridCalibrationTargetPointCloud should not call computeObservation, since it expects observation coordinates to be provided manually.");
  return false;
  }

}  // namespace cameras
}  // namespace aslam

//export explicit instantions for all included archives
#include <sm/boost/serialization.hpp>
#include <boost/serialization/export.hpp>
BOOST_CLASS_EXPORT_IMPLEMENT(aslam::cameras::GridCalibrationTargetPointCloud);
BOOST_CLASS_EXPORT_IMPLEMENT(aslam::cameras::GridCalibrationTargetPointCloud::PointCloudOptions);
