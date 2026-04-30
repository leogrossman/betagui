# -*- coding: utf-8 -*-

import configparser

class MCcalc:
    
    def __init__(self):
        self.load_calibration()
    
    def load_calibration(self):
        self.__cfg = configparser.ConfigParser()
        self.__cfg.read("calib.ini")
        self._Mdist = float(self.__cfg['saved_values']['mirror_distance'])
        self._Udist = float(self.__cfg['saved_values']['undulator_distance'])
        
        self._M1Y_pos = float(self.__cfg['saved_values']['M1Y_pos'])
        self._M1X_pos = float(self.__cfg['saved_values']['M1X_pos'])
        self._M1Y_neg = float(self.__cfg['saved_values']['M1Y_neg'])
        self._M1X_neg = float(self.__cfg['saved_values']['M1X_neg'])
        
        self._M2Y_pos = float(self.__cfg['saved_values']['M2Y_pos'])
        self._M2X_pos = float(self.__cfg['saved_values']['M2X_pos'])
        self._M2Y_neg = float(self.__cfg['saved_values']['M2Y_neg'])
        self._M2X_neg = float(self.__cfg['saved_values']['M2X_neg'])
        
        print('read from "calib.ini":')
        self.print_all()
        
    def print_all(self):
        print('Distance between mirrors (mm):', self._Mdist)
        print('Distance from mirror 2 to undulator centre (mm):', self._Udist)
        print('Mirror motor responses (microrad/step):')
        print('M1X+', self._M1X_pos)
        print('M1X-', self._M1X_neg)
        print('M1Y+', self._M1Y_pos)
        print('M1Y-', self._M1Y_neg)
        print('M2X+', self._M2X_pos)
        print('M2X-', self._M2X_neg)
        print('M2Y+', self._M2Y_pos)
        print('M2Y-', self._M2Y_neg)
        
#    def change_and_save(self):
#        self.__cfg['saved_values']['M1Y_pos'] = str(999.99)
#        with open("calib.ini", 'w') as calib:
#            self.__cfg.write(calib)
            
    def to_mirror_angles(self, offset, undulator_angle, axis=0):
        """
        Converts from ``offset`` and ``undulator_angle`` at the undulator centre to angles of both mirrors.
        ``axis`` = 0 calculates for the X (vertical) direction, otherwise for the Y (horizontal) direction.
        returns (angle_mirror_1, angle_mirror_2) where Mirror 1 is closer to the laser.
        """
        offset_angle = -offset / (2 * self._Mdist) * 10**6 # convert to microrads
        M1_undulator_angle = undulator_angle / 2 * self._Udist/self._Mdist
        M2_undulator_angle = undulator_angle / 2 + M1_undulator_angle
        
        M1_angle = M1_undulator_angle + offset_angle
        M2_angle = M2_undulator_angle + offset_angle
        if not axis: # i.e. axis == 0
            M2_angle *= -1
        
        return M1_angle, M2_angle
    
    
    def to_undulator_beam_pos(self, M1_angle, M2_angle, axis=0):
        """
        Converts from ``M1_angle`` and ``M2_angle`` (mirror 1 is closer to the laser) to offset and angle at the undulator centre.
        ``axis`` = 0 calculates for the X (vertical) direction, otherwise for the Y (horizontal) direction.
        returns (offset, undulator_angle).
        """
        if not axis: # i.e. axis == 0
            M2_angle *= -1
        undulator_angle = 2 * (M2_angle - M1_angle)
        offset = (undulator_angle * self._Udist - 2 * self._Mdist * M1_angle) / 10**6 # convert from microrads
        
        return offset, undulator_angle
    
    
    def angle_to_steps(self, angle_diff_1, angle_diff_2, axis=0):
        """
        Calculates the number of steps the mirrors need to be moved to achieve an angle change
        of ``angle_diff_1`` for mirror 1 and ``angle_diff_2`` for mirror 2
        (mirror 1 is closer to the laser).
        ``axis`` = 0 calculates for the X (vertical) direction, otherwise for the Y (horizontal) direction.
        returns (steps1, steps2).
        """
        steps1 = self.angle_to_steps_single(angle_diff_1, axis, True)
        steps2 = self.angle_to_steps_single(angle_diff_2, axis, False)
        return steps1, steps2
    
    
    def angle_to_steps_single(self, angle_diff, axis=0, mirror1=True):
        if angle_diff < 0:
            if not axis: # i.e. axis == 0
                if mirror1:
                    return angle_diff / self._M1X_neg
                else:
                    return angle_diff / self._M2X_neg
            else:
                if mirror1:
                    return angle_diff / self._M1Y_neg
                else:
                    return angle_diff / self._M2Y_neg
        else:
            if not axis: # i.e. axis == 0
                if mirror1:
                    return angle_diff / self._M1X_pos
                else:
                    return angle_diff / self._M2X_pos
            else:
                if mirror1:
                    return angle_diff / self._M1Y_pos
                else:
                    return angle_diff / self._M2Y_pos
                
                
    def steps_to_angle(self, step_diff_1, step_diff_2, axis=0):
        """
        Calculates the angle change for both mirrors when they are moved by
        ``step_diff_1`` (mirror 1) and ``step_diff_2`` (mirror 2). (mirror 1 is closer to the laser).
        ``axisX`` = 0 calculates for the X (vertical) direction, otherwise for the Y (horizontal) direction.
        returns (angle_diff_1, angle_diff_2).
        """
        angle_diff_1 = self.steps_to_angle_single(step_diff_1, axis, True)
        angle_diff_2 = self.steps_to_angle_single(step_diff_2, axis, False)
        return angle_diff_1, angle_diff_2
    
    
    def steps_to_angle_single(self, step_diff, axis=0, mirror1=True):
        if step_diff < 0:
            if not axis: # i.e. axis == 0
                if mirror1:
                    return step_diff * self._M1X_neg
                else:
                    return step_diff * self._M2X_neg
            else:
                if mirror1:
                    return step_diff * self._M1Y_neg
                else:
                    return step_diff * self._M2Y_neg
        else:
            if not axis: # i.e. axis == 0
                if mirror1:
                    return step_diff * self._M1X_pos
                else:
                    return step_diff * self._M2X_pos
            else:
                if mirror1:
                    return step_diff * self._M1Y_pos
                else:
                    return step_diff * self._M2Y_pos
